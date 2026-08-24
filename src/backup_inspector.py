"""Bounded, read-only inspection helpers for Home Assistant backup archives.

The scanner never extracts archive paths to disk. It reads only regular files,
enforces one aggregate budget across nested archives, and redacts common secret
forms before returning any explicitly requested content.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import multiprocessing
from pathlib import Path, PurePosixPath
import re
import tarfile
import time
from typing import Any, BinaryIO, Dict, Iterable, List, Sequence, Union


BACKUP_TEXT_EXTENSIONS = (
    ".yaml", ".yml", ".json", ".txt", ".md", ".j2", ".jinja",
    ".conf", ".ini", ".toml", ".env", ".csv", ".log",
)
BACKUP_TEXT_PATH_HINTS = (
    "automation", "script", "configuration", "customize", "group", "scene",
    "template", "node-red", "nodered", "lovelace", ".storage/",
)
BACKUP_ARCHIVE_EXTENSIONS = (".tar", ".tar.gz", ".tgz")
BACKUP_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class BackupValidationError(ValueError):
    """The request or archive violates a security boundary."""


class BackupLimitError(RuntimeError):
    """A bounded scan stopped after reaching a configured limit."""


@dataclass(frozen=True)
class BackupLimits:
    max_backups: int = 10
    max_patterns: int = 16
    max_pattern_chars: int = 128
    max_total_pattern_chars: int = 1024
    max_matches: int = 200
    max_context_lines: int = 3
    max_file_bytes: int = 2 * 1024 * 1024
    max_download_bytes: int = 128 * 1024 * 1024
    max_total_download_bytes: int = 256 * 1024 * 1024
    max_archive_members: int = 5_000
    max_unpacked_bytes: int = 256 * 1024 * 1024
    max_nested_archive_bytes: int = 32 * 1024 * 1024
    max_depth: int = 2
    max_seconds: float = 30.0
    max_concurrency: int = 1

    def public_dict(self) -> Dict[str, Any]:
        return {
            "max_backups": self.max_backups,
            "max_patterns": self.max_patterns,
            "max_pattern_chars": self.max_pattern_chars,
            "max_matches": self.max_matches,
            "max_context_lines": self.max_context_lines,
            "max_file_bytes": self.max_file_bytes,
            "max_download_bytes": self.max_download_bytes,
            "max_total_download_bytes": self.max_total_download_bytes,
            "max_archive_members": self.max_archive_members,
            "max_unpacked_bytes": self.max_unpacked_bytes,
            "max_nested_archive_bytes": self.max_nested_archive_bytes,
            "max_depth": self.max_depth,
            "max_seconds": self.max_seconds,
            "max_concurrency": self.max_concurrency,
        }


@dataclass
class ScanBudget:
    limits: BackupLimits
    deadline: float
    archive_members: int = 0
    unpacked_bytes: int = 0
    archives_scanned: int = 0
    files_scanned: int = 0
    large_files_skipped: int = 0
    non_text_files_skipped: int = 0
    unsafe_members_skipped: int = 0

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise BackupLimitError("backup scan exceeded its time limit")

    def account_member(self, size: int) -> None:
        self.check_time()
        self.archive_members += 1
        if self.archive_members > self.limits.max_archive_members:
            raise BackupLimitError("backup scan exceeded the archive-member limit")
        if size < 0:
            raise BackupValidationError("archive member has a negative size")
        self.unpacked_bytes += size
        if self.unpacked_bytes > self.limits.max_unpacked_bytes:
            raise BackupLimitError("backup scan exceeded the aggregate unpacked-byte limit")

    def stats(self) -> Dict[str, int]:
        return {
            "archives_scanned": self.archives_scanned,
            "archive_members": self.archive_members,
            "unpacked_bytes_accounted": self.unpacked_bytes,
            "files_scanned": self.files_scanned,
            "large_files_skipped": self.large_files_skipped,
            "non_text_files_skipped": self.non_text_files_skipped,
            "unsafe_members_skipped": self.unsafe_members_skipped,
        }


def validate_backup_slug(slug: Any) -> str:
    value = str(slug or "")
    if not BACKUP_SLUG_RE.fullmatch(value):
        raise BackupValidationError(
            "backup slug must contain 1-64 ASCII letters, digits, underscores, or hyphens"
        )
    return value


def normalize_patterns(
    patterns: Union[str, Sequence[str]], limits: BackupLimits
) -> List[str]:
    if isinstance(patterns, str):
        candidates: Iterable[Any] = [patterns]
    elif isinstance(patterns, Sequence):
        candidates = patterns
    else:
        raise BackupValidationError("patterns must be a string or an array of strings")

    normalized = [str(pattern).strip() for pattern in candidates]
    if not normalized or any(not pattern for pattern in normalized):
        raise BackupValidationError("patterns must contain non-empty search strings")
    if len(normalized) > limits.max_patterns:
        raise BackupLimitError("too many backup search patterns")
    if any("\x00" in pattern or len(pattern) > limits.max_pattern_chars for pattern in normalized):
        raise BackupLimitError("a backup search pattern is too long or contains NUL")
    if sum(len(pattern) for pattern in normalized) > limits.max_total_pattern_chars:
        raise BackupLimitError("backup search patterns exceed the total character limit")
    return normalized


_KEY_VALUE_SECRET_RE = re.compile(
    r"(?ix)("
    r"(?<![A-Za-z0-9_-])[\"']?[A-Za-z0-9_-]*"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|"
    r"client[_-]?secret|secret|authorization|private[_-]?key|credentials?)"
    r"[A-Za-z0-9_-]*[\"']?(?![A-Za-z0-9_-])\s*[:=]\s*"
    r")[^\r\n]*"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@")
_PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?"
    r"(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_KNOWN_TOKEN_RE = re.compile(
    r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,})\b"
)
_HIGH_ENTROPY_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{40,}(?![A-Za-z0-9+/=_-])"
)


def redact_sensitive_text(value: Any) -> str:
    text = str(value)
    text = _PRIVATE_KEY_BLOCK_RE.sub("[REDACTED_PRIVATE_KEY_BLOCK]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _KEY_VALUE_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = _JWT_RE.sub("[REDACTED_JWT]", text)
    text = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", text)
    text = _KNOWN_TOKEN_RE.sub("[REDACTED_TOKEN]", text)
    text = _HIGH_ENTROPY_VALUE_RE.sub("[REDACTED_HIGH_ENTROPY_VALUE]", text)
    return text


def _safe_member_name(name: str) -> bool:
    if not name or "\x00" in name or len(name) > 512 or name.startswith(("/", "\\")):
        return False
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return not path.is_absolute() and ".." not in path.parts


def _is_text_member(name: str) -> bool:
    lower_name = name.lower()
    return lower_name.endswith(BACKUP_TEXT_EXTENSIONS) or any(
        hint in lower_name for hint in BACKUP_TEXT_PATH_HINTS
    )


def _is_nested_archive(name: str) -> bool:
    return name.lower().endswith(BACKUP_ARCHIVE_EXTENSIONS)


def _line_matches(line: str, patterns: Sequence[str], match_mode: str) -> bool:
    lowered = line.casefold()
    checks = [pattern.casefold() in lowered for pattern in patterns]
    return all(checks) if match_mode == "all" else any(checks)


def _collect_matches(
    text: str,
    patterns: Sequence[str],
    match_mode: str,
    source_path: str,
    remaining: int,
    include_content: bool,
    context_lines: int,
) -> List[Dict[str, Any]]:
    lines = text.splitlines()
    matches: List[Dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not _line_matches(line, patterns, match_mode):
            continue
        item: Dict[str, Any] = {"path": source_path, "line": index + 1}
        if include_content:
            start = max(0, index - context_lines)
            end = min(len(lines), index + context_lines + 1)
            snippet = redact_sensitive_text("\n".join(lines[start:end]))
            item["snippet"] = snippet[:2_000]
        matches.append(item)
        if len(matches) >= remaining:
            break
    return matches


def _read_bounded(member_file: BinaryIO, maximum: int) -> bytes:
    data = member_file.read(maximum + 1)
    if len(data) > maximum:
        raise BackupLimitError("archive member exceeds its read limit")
    return data


def _scan_archive(
    archive_source: Union[Path, BytesIO],
    label: str,
    patterns: Sequence[str],
    match_mode: str,
    max_matches: int,
    include_content: bool,
    context_lines: int,
    budget: ScanBudget,
    matches: List[Dict[str, Any]],
    errors: List[Dict[str, str]],
    depth: int,
) -> None:
    budget.check_time()
    budget.archives_scanned += 1
    try:
        if isinstance(archive_source, Path):
            archive_context = tarfile.open(archive_source, "r:*")
        else:
            archive_context = tarfile.open(fileobj=archive_source, mode="r:*")

        with archive_context as archive:
            for member in archive:
                budget.account_member(member.size if member.isfile() else 0)
                if len(matches) >= max_matches:
                    return
                if not _safe_member_name(member.name):
                    budget.unsafe_members_skipped += 1
                    errors.append({"archive": label, "error": "unsafe archive member path skipped"})
                    continue
                if not member.isfile():
                    continue

                member_label = f"{label}!{member.name}"
                if _is_nested_archive(member.name):
                    if depth >= budget.limits.max_depth:
                        errors.append({"archive": member_label, "error": "nested archive depth limit reached"})
                        continue
                    if member.size > budget.limits.max_nested_archive_bytes:
                        errors.append({"archive": member_label, "error": "nested archive byte limit exceeded"})
                        continue
                    member_file = archive.extractfile(member)
                    if member_file is None:
                        continue
                    nested_bytes = _read_bounded(member_file, budget.limits.max_nested_archive_bytes)
                    _scan_archive(
                        BytesIO(nested_bytes), member_label, patterns, match_mode,
                        max_matches, include_content, context_lines, budget, matches,
                        errors, depth + 1,
                    )
                    continue

                if not _is_text_member(member.name):
                    budget.non_text_files_skipped += 1
                    continue
                if member.size > budget.limits.max_file_bytes:
                    budget.large_files_skipped += 1
                    continue

                member_file = archive.extractfile(member)
                if member_file is None:
                    continue
                raw = _read_bounded(member_file, budget.limits.max_file_bytes)
                if b"\x00" in raw[:4096]:
                    budget.non_text_files_skipped += 1
                    continue
                text = raw.decode("utf-8", errors="replace")
                budget.files_scanned += 1
                matches.extend(_collect_matches(
                    text, patterns, match_mode, member_label,
                    max_matches - len(matches), include_content, context_lines,
                ))
    except (tarfile.TarError, OSError, UnicodeError, BackupValidationError) as exc:
        errors.append({"archive": label, "error": redact_sensitive_text(exc)})


def scan_backup_archive(
    archive_path: Union[str, Path],
    patterns: Sequence[str],
    limits: BackupLimits,
    *,
    match_mode: str = "any",
    max_matches: int = 100,
    include_content: bool = False,
    context_lines: int = 0,
) -> Dict[str, Any]:
    """Synchronously scan one archive; callers should run this in a worker."""
    if match_mode not in {"any", "all"}:
        raise BackupValidationError("match_mode must be 'any' or 'all'")
    if not 1 <= max_matches <= limits.max_matches:
        raise BackupLimitError("max_matches is outside the allowed range")
    if not 0 <= context_lines <= limits.max_context_lines:
        raise BackupLimitError("context_lines is outside the allowed range")

    normalized_patterns = normalize_patterns(patterns, limits)
    budget = ScanBudget(limits=limits, deadline=time.monotonic() + limits.max_seconds)
    matches: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    truncated = False
    try:
        _scan_archive(
            Path(archive_path), Path(archive_path).name, normalized_patterns,
            match_mode, max_matches, include_content, context_lines, budget,
            matches, errors, 0,
        )
    except BackupLimitError as exc:
        truncated = True
        errors.append({"archive": Path(archive_path).name, "error": str(exc)})

    return {
        "matches": matches[:max_matches],
        "errors": errors,
        "stats": budget.stats(),
        "truncated": truncated or len(matches) >= max_matches,
    }


def _isolated_scan_worker(connection: Any, args: tuple, kwargs: Dict[str, Any]) -> None:
    try:
        connection.send(("ok", scan_backup_archive(*args, **kwargs)))
    except BaseException as exc:  # The parent must receive a bounded, serializable failure.
        connection.send(("error", redact_sensitive_text(exc)))
    finally:
        connection.close()


def scan_backup_archive_isolated(
    archive_path: Union[str, Path],
    patterns: Sequence[str],
    limits: BackupLimits,
    *,
    match_mode: str = "any",
    max_matches: int = 100,
    include_content: bool = False,
    context_lines: int = 0,
) -> Dict[str, Any]:
    """Scan in a disposable process so the wall-clock ceiling is enforceable."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    args = (archive_path, patterns, limits)
    kwargs = {
        "match_mode": match_mode,
        "max_matches": max_matches,
        "include_content": include_content,
        "context_lines": context_lines,
    }
    process = context.Process(
        target=_isolated_scan_worker,
        args=(sender, args, kwargs),
        name="ha-backup-archive-scan",
        daemon=True,
    )
    process.start()
    sender.close()
    try:
        if not receiver.poll(limits.max_seconds):
            process.terminate()
            process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
            raise BackupLimitError("backup scan exceeded its hard wall-clock limit")
        try:
            status, payload = receiver.recv()
        except EOFError as exc:
            raise RuntimeError("backup scan worker exited without a result") from exc
        process.join(timeout=1.0)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
        if status != "ok":
            raise RuntimeError(f"backup scan worker failed: {payload}")
        return payload
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=1.0)
        else:
            process.join(timeout=0.1)
