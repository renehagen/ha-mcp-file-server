import os
import json
import logging
import asyncio
import pathlib
import re
import secrets
import shlex
import tempfile
from dataclasses import replace
from typing import Dict, List, Any, Optional, Union
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
from datetime import datetime, timedelta, timezone
import paho.mqtt.client as mqtt
import time

from backup_inspector import (
    BackupLimitError,
    BackupLimits,
    BackupValidationError,
    normalize_patterns,
    redact_sensitive_text,
    scan_backup_archive_isolated,
    validate_backup_slug,
)
from file_handler import FileHandler
from supervisor_api import SupervisorAPI
from yaml_validator import YAMLValidator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment
VERSION = "1.6.0"
PORT = int(os.getenv("MCP_PORT", "6789"))
API_KEY = os.getenv("MCP_API_KEY", "")
READ_ONLY = os.getenv("MCP_READ_ONLY", "false").lower() == "true"
MAX_FILE_SIZE_MB = int(os.getenv("MCP_MAX_FILE_SIZE_MB", "10"))
ENABLE_HA_CLI = os.getenv("MCP_ENABLE_HA_CLI", "false").lower() == "true"
ENABLE_BACKUP_INSPECTION = os.getenv("MCP_ENABLE_BACKUP_INSPECTION", "false").lower() == "true"
BACKUP_ALLOW_CONTENT = os.getenv("MCP_BACKUP_ALLOW_CONTENT", "false").lower() == "true"
MCP_ADDON_SLUG = os.getenv("MCP_ADDON_SLUG", "local_mcp_file_server")
MQTT_BROKER = os.getenv("MQTT_BROKER", "192.168.1.78")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")

MIN_BACKUP_API_KEY_LENGTH = 24
MIN_BACKUP_API_KEY_UNIQUE_CHARACTERS = 8
_configured_backup_download_mb = int(os.getenv("MCP_BACKUP_MAX_DOWNLOAD_MB", "128"))
_backup_download_mb = max(1, min(_configured_backup_download_mb, 128))
BACKUP_LIMITS = BackupLimits(
    max_download_bytes=_backup_download_mb * 1024 * 1024,
    max_total_download_bytes=min(_backup_download_mb * 2, 256) * 1024 * 1024,
)
_BACKUP_SEARCH_SEMAPHORE = asyncio.Semaphore(BACKUP_LIMITS.max_concurrency)

DEFAULT_ALLOWED_SERVICES = [
    "automation.reload",
    "automation.turn_on",
    "automation.turn_off",
    "script.reload",
    "template.reload",
    "python_script.reload",
    "homeassistant.check_config",
    "homeassistant.reload_config_entry",
    "homeassistant.update_entity",
    "number.set_value",
    "select.select_option",
]

# Parse allowed directories - bashio provides them as newline-separated values
allowed_dirs_env = os.getenv("MCP_ALLOWED_DIRS", "")
if allowed_dirs_env.strip():
    try:
        ALLOWED_DIRS = json.loads(allowed_dirs_env)
    except json.JSONDecodeError:
        ALLOWED_DIRS = [d.strip() for d in allowed_dirs_env.strip().split('\n') if d.strip()]
else:
    ALLOWED_DIRS = []

allowed_services_env = os.getenv("MCP_ALLOWED_SERVICES", "")
if allowed_services_env.strip():
    try:
        parsed_allowed_services = json.loads(allowed_services_env)
        ALLOWED_SERVICES = parsed_allowed_services if isinstance(parsed_allowed_services, list) else DEFAULT_ALLOWED_SERVICES
    except json.JSONDecodeError:
        ALLOWED_SERVICES = [s.strip() for s in allowed_services_env.strip().split('\n') if s.strip()]
else:
    ALLOWED_SERVICES = DEFAULT_ALLOWED_SERVICES

# Initialize FastAPI app
app = FastAPI(title="MCP File Server", version=VERSION)

# Initialize file handler
file_handler = FileHandler(
    allowed_dirs=ALLOWED_DIRS,
    read_only=READ_ONLY,
    max_file_size_mb=MAX_FILE_SIZE_MB
)
yaml_validator = YAMLValidator(file_handler)

# JSON-RPC 2.0 Models
class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Dict[str, Any]] = None

class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

def verify_function_key(code: str):
    """Verify function key like Azure Functions."""
    supplied = "" if code is None else str(code)
    if API_KEY and not secrets.compare_digest(supplied, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid function key")
    return True

def require_ha_cli_enabled():
    """Ensure Home Assistant API tools are enabled."""
    if not ENABLE_HA_CLI:
        raise Exception("HA CLI commands are disabled. Set MCP_ENABLE_HA_CLI=true to enable.")

def backup_api_key_is_strong() -> bool:
    key = API_KEY.strip()
    return (
        len(key) >= MIN_BACKUP_API_KEY_LENGTH
        and len(set(key)) >= MIN_BACKUP_API_KEY_UNIQUE_CHARACTERS
        and key.casefold() not in {"change-me", "changeme", "your_api_key"}
    )

def backup_access_ready() -> bool:
    """Return whether the runtime is safely configured to expose backup tools."""
    return (
        ENABLE_HA_CLI
        and ENABLE_BACKUP_INSPECTION
        and backup_api_key_is_strong()
    )

def require_backup_access(
    *, include_content: bool = False, acknowledge_sensitive_content: bool = False
) -> None:
    """Require explicit enablement and strong authentication for backup access."""
    if type(include_content) is not bool:
        raise BackupValidationError("include_content must be a JSON boolean")
    if type(acknowledge_sensitive_content) is not bool:
        raise BackupValidationError(
            "acknowledge_sensitive_content must be a JSON boolean"
        )
    require_ha_cli_enabled()
    if not ENABLE_BACKUP_INSPECTION:
        raise PermissionError("Backup inspection is disabled. Enable it explicitly first.")
    if not backup_api_key_is_strong():
        raise PermissionError(
            "Backup inspection requires a non-placeholder API key of at least "
            f"{MIN_BACKUP_API_KEY_LENGTH} characters with sufficient variation."
        )
    if include_content is True and not BACKUP_ALLOW_CONTENT:
        raise PermissionError("Backup content return is disabled by configuration.")
    if include_content is True and acknowledge_sensitive_content is not True:
        raise PermissionError(
            "Returning redacted backup snippets requires acknowledge_sensitive_content=true."
        )

def require_ha_write_allowed():
    """Ensure Home Assistant write operations are permitted."""
    require_ha_cli_enabled()
    if READ_ONLY:
        raise Exception("Server is in read-only mode; Home Assistant write/reload tools are disabled.")

def ensure_service_allowed(domain: str, service: str):
    """Validate that a Home Assistant service is allowed by configuration."""
    service_key = f"{domain}.{service}"
    allowed = set(ALLOWED_SERVICES)
    if "*" in allowed or service_key in allowed or f"{domain}.*" in allowed:
        return
    raise Exception(
        f"Service '{service_key}' is not allowed. Configure MCP_ALLOWED_SERVICES/allowed_services to permit it."
    )

async def call_allowed_service(
    domain: str,
    service: str,
    target: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    return_response: bool = False
) -> Dict[str, Any]:
    """Call a Home Assistant service after applying write and allowlist checks."""
    require_ha_write_allowed()
    ensure_service_allowed(domain, service)
    supervisor_api = SupervisorAPI()
    return await supervisor_api.call_service(
        domain=domain,
        service=service,
        target=target or {},
        data=data or {},
        return_response=return_response
    )

def _json_text_result(payload: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}

def _extract_backup_items(response: Any) -> List[Dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    items = (
        data.get("backups") or data.get("snapshots")
        or response.get("backups") or response.get("snapshots") or []
    )
    return [item for item in items if isinstance(item, dict)]

def _summarize_backup_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return useful metadata without exposing backup content/config lists."""
    return {
        "slug": item.get("slug"),
        "name": item.get("name"),
        "date": item.get("date") or item.get("created") or item.get("last_modified"),
        "type": item.get("type"),
        "size": item.get("size"),
        "protected": item.get("protected"),
        "encrypted": item.get("encrypted"),
        "compressed": item.get("compressed"),
    }

def _backup_sort_key(item: Dict[str, Any]) -> str:
    return str(item.get("date") or item.get("created") or item.get("last_modified") or "")

def _bounded_backup_int(name: str, value: Any, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise BackupValidationError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise BackupValidationError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise BackupLimitError(f"{name} must be between {minimum} and {maximum}")
    return parsed

async def list_ha_backups() -> Dict[str, Any]:
    """List backup metadata behind the dedicated security gate."""
    require_backup_access()
    try:
        response = await asyncio.wait_for(
            SupervisorAPI().list_backups(), timeout=BACKUP_LIMITS.max_seconds
        )
    except asyncio.TimeoutError as exc:
        raise BackupLimitError("backup listing exceeded its time limit") from exc
    backups = sorted(_extract_backup_items(response), key=_backup_sort_key, reverse=True)
    safe_backups = []
    for item in backups[:BACKUP_LIMITS.max_backups]:
        summary = _summarize_backup_item(item)
        slug = summary.get("slug")
        try:
            summary["slug"] = validate_backup_slug(slug)
        except BackupValidationError:
            summary["slug"] = None
            summary["metadata_error"] = "Supervisor returned an invalid backup slug"
        safe_backups.append(summary)
    return {
        "timestamp": datetime.now().astimezone().isoformat(),
        "count": len(safe_backups),
        "available_count": len(backups),
        "truncated": len(backups) > len(safe_backups),
        "backups": safe_backups,
    }

async def get_ha_backup_info(slug: str) -> Dict[str, Any]:
    """Return one backup's bounded, sanitized metadata only."""
    slug = validate_backup_slug(slug)
    listing = await list_ha_backups()
    match = next((item for item in listing["backups"] if item.get("slug") == slug), None)
    if match is None:
        raise BackupValidationError("backup was not found in the bounded backup listing")
    return {
        "timestamp": listing["timestamp"],
        "backup": match,
    }

async def _search_ha_backups_impl(
    patterns: Union[str, List[str]],
    backup_slugs: Optional[List[str]],
    max_backups: int,
    max_matches: int,
    include_content: bool,
    acknowledge_sensitive_content: bool,
    context_lines: int,
    match_mode: str,
) -> Dict[str, Any]:
    require_backup_access(
        include_content=include_content,
        acknowledge_sensitive_content=acknowledge_sensitive_content,
    )
    normalized_patterns = normalize_patterns(patterns, BACKUP_LIMITS)
    if match_mode not in {"any", "all"}:
        raise BackupValidationError("match_mode must be 'any' or 'all'")
    max_backups = _bounded_backup_int(
        "max_backups", max_backups, 1, BACKUP_LIMITS.max_backups
    )
    max_matches = _bounded_backup_int(
        "max_matches", max_matches, 1, BACKUP_LIMITS.max_matches
    )
    context_lines = _bounded_backup_int(
        "context_lines", context_lines, 0, BACKUP_LIMITS.max_context_lines
    )

    requested_slugs = [validate_backup_slug(slug) for slug in (backup_slugs or [])]
    if len(requested_slugs) > BACKUP_LIMITS.max_backups:
        raise BackupLimitError("too many backup slugs requested")
    if len(set(requested_slugs)) != len(requested_slugs):
        raise BackupValidationError("backup_slugs must not contain duplicates")

    deadline = time.monotonic() + BACKUP_LIMITS.max_seconds
    supervisor_api = SupervisorAPI()
    try:
        backups_response = await asyncio.wait_for(
            supervisor_api.list_backups(),
            timeout=max(0.001, deadline - time.monotonic()),
        )
    except asyncio.TimeoutError as exc:
        raise BackupLimitError("backup request exceeded its time limit while listing backups") from exc
    all_backups = sorted(
        _extract_backup_items(backups_response), key=_backup_sort_key, reverse=True
    )
    requested_set = set(requested_slugs)
    selected = [
        item for item in all_backups
        if not requested_set or item.get("slug") in requested_set
    ][:max_backups]

    aggregate_stats = {
        "downloads": 0,
        "downloaded_bytes": 0,
        "archives_scanned": 0,
        "archive_members": 0,
        "unpacked_bytes_accounted": 0,
        "files_scanned": 0,
        "large_files_skipped": 0,
        "non_text_files_skipped": 0,
        "unsafe_members_skipped": 0,
    }
    all_matches: List[Dict[str, Any]] = []
    all_errors: List[Dict[str, str]] = []
    results = []
    with tempfile.TemporaryDirectory(prefix="ha-backup-search-") as temp_dir:
        for backup in selected:
            if len(all_matches) >= max_matches:
                break
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                all_errors.append({"error": "backup request exceeded its time limit"})
                break
            slug = validate_backup_slug(backup.get("slug"))
            result = {"backup": _summarize_backup_item(backup), "matches": [], "errors": []}
            archive_path = pathlib.Path(temp_dir) / f"{slug}.tar"
            remaining_download = (
                BACKUP_LIMITS.max_total_download_bytes - aggregate_stats["downloaded_bytes"]
            )
            if remaining_download <= 0:
                error = {"backup_slug": slug, "error": "aggregate download-byte limit reached"}
                result["errors"].append(error)
                all_errors.append(error)
                results.append(result)
                break
            try:
                await supervisor_api.download_backup(
                    slug,
                    str(archive_path),
                    max_bytes=min(BACKUP_LIMITS.max_download_bytes, remaining_download),
                    timeout_seconds=min(remaining_seconds, BACKUP_LIMITS.max_seconds),
                )
                downloaded_bytes = archive_path.stat().st_size
                if downloaded_bytes > min(BACKUP_LIMITS.max_download_bytes, remaining_download):
                    raise BackupLimitError("downloaded backup exceeds the active byte limit")
                aggregate_stats["downloads"] += 1
                aggregate_stats["downloaded_bytes"] += downloaded_bytes

                remaining_members = (
                    BACKUP_LIMITS.max_archive_members - aggregate_stats["archive_members"]
                )
                remaining_unpacked = (
                    BACKUP_LIMITS.max_unpacked_bytes
                    - aggregate_stats["unpacked_bytes_accounted"]
                )
                if remaining_members <= 0 or remaining_unpacked <= 0:
                    raise BackupLimitError("aggregate archive scan budget exhausted")
                scan_seconds = deadline - time.monotonic()
                if scan_seconds <= 0:
                    raise BackupLimitError("backup request exceeded its time limit")
                scan_limits = replace(
                    BACKUP_LIMITS,
                    max_archive_members=remaining_members,
                    max_unpacked_bytes=remaining_unpacked,
                    max_seconds=scan_seconds,
                )
                scan = await asyncio.to_thread(
                    scan_backup_archive_isolated,
                    archive_path,
                    normalized_patterns,
                    scan_limits,
                    match_mode=match_mode,
                    max_matches=max_matches - len(all_matches),
                    include_content=include_content,
                    context_lines=context_lines,
                )
                result["matches"] = scan["matches"]
                result["errors"] = scan["errors"]
                result["stats"] = scan["stats"]
                result["truncated"] = scan["truncated"]
                all_matches.extend(scan["matches"])
                all_errors.extend(scan["errors"])
                for key, value in scan["stats"].items():
                    aggregate_stats[key] += value
            except Exception as exc:
                error = {"backup_slug": slug, "error": redact_sensitive_text(exc)}
                result["errors"].append(error)
                all_errors.append(error)
            finally:
                archive_path.unlink(missing_ok=True)
            results.append(result)

    missing = sorted(requested_set - {item.get("slug") for item in selected})
    return {
        "timestamp": datetime.now().astimezone().isoformat(),
        "pattern_count": len(normalized_patterns),
        "match_mode": match_mode,
        "include_content": include_content,
        "requested_backup_slugs": requested_slugs,
        "missing_backup_slugs": missing,
        "selected_backup_count": len(selected),
        "total_matches": len(all_matches),
        "stats": aggregate_stats,
        "limits": BACKUP_LIMITS.public_dict(),
        "errors": all_errors,
        "results": results,
    }

async def search_ha_backups(
    patterns: Union[str, List[str]],
    backup_slugs: Optional[List[str]] = None,
    max_backups: int = 5,
    max_matches: int = 100,
    include_content: bool = False,
    acknowledge_sensitive_content: bool = False,
    context_lines: int = 0,
    match_mode: str = "any",
) -> Dict[str, Any]:
    """Run one bounded search at a time and reject excess concurrent work."""
    try:
        await asyncio.wait_for(_BACKUP_SEARCH_SEMAPHORE.acquire(), timeout=1.0)
    except asyncio.TimeoutError as exc:
        raise BackupLimitError("another backup search is already running") from exc
    try:
        try:
            return await asyncio.wait_for(
                _search_ha_backups_impl(
                    patterns, backup_slugs, max_backups, max_matches, include_content,
                    acknowledge_sensitive_content, context_lines, match_mode,
                ),
                timeout=BACKUP_LIMITS.max_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise BackupLimitError("backup request exceeded its hard time limit") from exc
    finally:
        _BACKUP_SEARCH_SEMAPHORE.release()

def _extract_trace_runs(trace_list: Any) -> List[Dict[str, Any]]:
    """Normalize HA trace/list output into a list of run metadata."""
    if isinstance(trace_list, list):
        return trace_list
    if isinstance(trace_list, dict):
        for key in ("traces", "trace", "items", "runs"):
            value = trace_list.get(key)
            if isinstance(value, list):
                return value
        return [
            {"run_id": run_id, **metadata} if isinstance(metadata, dict) else {"run_id": run_id, "value": metadata}
            for run_id, metadata in trace_list.items()
        ]
    return []

def _get_nested_value(data: Any, path: List[Any]) -> Any:
    current = data
    for part in path:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and isinstance(part, int) and part < len(current):
            current = current[part]
        else:
            return None
    return current

def _summarize_trace_step(step_path: str, step: Dict[str, Any], summary: Dict[str, Any]):
    variables = step.get("variables") or _get_nested_value(step, ["result", "variables"])
    if variables:
        summary["variables"].append({
            "path": step_path,
            "variables": variables
        })

    result = step.get("result", {})
    if isinstance(result, dict):
        choice = result.get("choice") or result.get("choose")
        if choice is not None:
            summary["chosen_paths"].append({
                "path": step_path,
                "choice": choice
            })

    error = step.get("error") or step.get("exception") or _get_nested_value(step, ["result", "error"])
    if error:
        summary["errors"].append({
            "path": step_path,
            "error": error
        })

    service_call = step.get("service") or _get_nested_value(step, ["result", "service"])
    if service_call:
        summary["service_calls"].append({
            "path": step_path,
            "service": service_call,
            "target": step.get("target") or _get_nested_value(step, ["result", "target"]),
            "data": step.get("service_data") or step.get("data") or _get_nested_value(step, ["result", "service_data"]),
        })

def _walk_trace_steps(value: Any, summary: Dict[str, Any], path: str = ""):
    if isinstance(value, dict):
        if any(key in value for key in ("variables", "result", "error", "exception", "service", "service_data")):
            _summarize_trace_step(path or "trace", value, summary)
        for key, child in value.items():
            child_path = f"{path}/{key}" if path else str(key)
            _walk_trace_steps(child, summary, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}/{index}" if path else str(index)
            _walk_trace_steps(child, summary, child_path)

def normalize_automation_trace(run_id: str, trace: Any, trace_metadata: Dict[str, Any], include_raw: bool) -> Dict[str, Any]:
    """Reduce a raw Home Assistant trace to the fields useful for automation debugging."""
    summary = {
        "run_id": run_id,
        "timestamp": trace_metadata.get("timestamp") or trace_metadata.get("last_step") or trace_metadata.get("run_id"),
        "trigger": None,
        "chosen_paths": [],
        "variables": [],
        "service_calls": [],
        "errors": [],
    }

    if isinstance(trace, dict):
        summary["trigger"] = (
            _get_nested_value(trace, ["trace", "trigger"])
            or _get_nested_value(trace, ["trigger"])
            or _get_nested_value(trace, ["context", "trigger"])
        )
        _walk_trace_steps(trace, summary)

    if include_raw:
        summary["raw"] = trace

    return summary

async def get_automation_trace_summary(entity_id: str, last_n: int = 5, include_raw: bool = False) -> Dict[str, Any]:
    """Fetch and normalize recent automation traces for one automation entity."""
    require_ha_cli_enabled()
    if not entity_id.startswith("automation."):
        raise Exception("entity_id must be an automation entity, for example automation.my_automation")

    supervisor_api = SupervisorAPI()
    state_response = await supervisor_api.get_state(entity_id)
    state = state_response.get("state", {})
    item_id = state.get("attributes", {}).get("id") or entity_id.split(".", 1)[1]
    trace_list = await supervisor_api.list_traces("automation", item_id)
    runs = _extract_trace_runs(trace_list)

    selected_runs = runs[:max(last_n, 0)]
    traces = []
    for run in selected_runs:
        run_id = str(run.get("run_id") or run.get("id") or run.get("trace_id") or "")
        if not run_id:
            continue
        raw_trace = await supervisor_api.get_trace("automation", item_id, run_id)
        traces.append(normalize_automation_trace(run_id, raw_trace, run, include_raw))

    return {
        "entity_id": entity_id,
        "item_id": item_id,
        "requested": last_n,
        "returned": len(traces),
        "traces": traces,
    }

LOG_LINE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?) "
    r"(?P<level>[A-Z]+) "
    r"\((?P<thread>[^)]*)\) "
    r"\[(?P<logger>[^\]]+)\] "
    r"(?P<message>.*)$"
)

def _parse_relative_or_iso_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    value = value.strip()
    now = datetime.now().astimezone()
    if value.lower() == "now":
        return now

    relative_match = re.match(r"^-(\d+)([mhdw])$", value.lower())
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        if unit == "m":
            return now - timedelta(minutes=amount)
        if unit == "h":
            return now - timedelta(hours=amount)
        if unit == "d":
            return now - timedelta(days=amount)
        if unit == "w":
            return now - timedelta(weeks=amount)

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone() if parsed.tzinfo else parsed.astimezone()

def _parse_log_timestamp(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone() if parsed.tzinfo else parsed.astimezone()
    except ValueError:
        return None

def _normalize_filter_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)]

def _matches_patterns(text: str, patterns: List[str], match_mode: str = "any") -> bool:
    if not patterns:
        return True

    text_lower = text.lower()
    checks = [pattern.lower() in text_lower for pattern in patterns]
    return all(checks) if match_mode == "all" else any(checks)

async def query_logs(
    path: str = "/config/home-assistant.log",
    since: Optional[str] = None,
    level: Optional[Any] = None,
    logger_filter: Optional[Any] = None,
    text_filter: Optional[Any] = None,
    limit: int = 200,
    max_bytes: int = 2 * 1024 * 1024,
    match_mode: str = "any"
) -> Dict[str, Any]:
    """Query Home Assistant logs from the tail with structured filters."""
    since_dt = _parse_relative_or_iso_time(since)
    levels = {item.upper() for item in _normalize_filter_list(level)}
    logger_patterns = _normalize_filter_list(logger_filter)
    text_patterns = _normalize_filter_list(text_filter)
    match_mode = match_mode if match_mode in {"any", "all"} else "any"

    tail = await file_handler.read_tail_bytes(path, max_bytes=max_bytes)
    records = []
    current = None

    for line_number, line in enumerate(tail["lines"], 1):
        match = LOG_LINE_RE.match(line)
        if match:
            if current:
                records.append(current)
            timestamp = match.group("timestamp")
            timestamp_dt = _parse_log_timestamp(timestamp)
            current = {
                "line_number": line_number,
                "timestamp": timestamp,
                "timestamp_local": timestamp_dt.isoformat() if timestamp_dt else None,
                "timestamp_utc": timestamp_dt.astimezone(timezone.utc).isoformat() if timestamp_dt else None,
                "level": match.group("level"),
                "thread": match.group("thread"),
                "logger": match.group("logger"),
                "message": match.group("message"),
                "_timestamp_dt": timestamp_dt,
            }
        elif current:
            current["message"] += "\n" + line

    if current:
        records.append(current)

    matches = []
    scanned_records = 0
    for record in reversed(records):
        scanned_records += 1
        record_dt = record.get("_timestamp_dt")
        if since_dt and record_dt and record_dt < since_dt:
            break

        if levels and record.get("level", "").upper() not in levels:
            continue

        if not _matches_patterns(record.get("logger", ""), logger_patterns, match_mode):
            continue

        combined_text = f"{record.get('logger', '')} {record.get('message', '')}"
        if not _matches_patterns(combined_text, text_patterns, match_mode):
            continue

        public_record = {key: value for key, value in record.items() if key != "_timestamp_dt"}
        matches.append(public_record)
        if len(matches) >= limit:
            break

    return {
        "path": tail["path"],
        "since": since,
        "level": sorted(levels) if levels else None,
        "logger_filter": logger_patterns,
        "text_filter": text_patterns,
        "match_mode": match_mode,
        "limit": limit,
        "max_bytes": max_bytes,
        "bytes_read": tail["bytes_read"],
        "truncated_from_start": tail["truncated_from_start"],
        "scanned_records": scanned_records,
        "returned_count": len(matches),
        "order": "newest_first",
        "lines": matches,
    }

def get_mcp_runtime_status() -> Dict[str, Any]:
    """Return the effective runtime configuration for this MCP server."""
    return {
        "status": "healthy",
        "version": VERSION,
        "mcp_addon_slug": MCP_ADDON_SLUG,
        "read_only": READ_ONLY,
        "ha_cli_enabled": ENABLE_HA_CLI,
        "backup_inspection_enabled": ENABLE_BACKUP_INSPECTION,
        "backup_access_ready": backup_access_ready(),
        "backup_content_return_enabled": BACKUP_ALLOW_CONTENT,
        "backup_limits": BACKUP_LIMITS.public_dict(),
        "allowed_dirs": ALLOWED_DIRS,
        "allowed_services": ALLOWED_SERVICES,
        "max_file_size_mb": MAX_FILE_SIZE_MB,
        "mcp_endpoint": "/api/mcp",
        "timestamp": datetime.now().astimezone().isoformat(),
    }

def _tail_text_lines(text: str, line_limit: int = 200) -> Dict[str, Any]:
    lines = text.splitlines()
    if line_limit < 0:
        selected = lines
    else:
        selected = lines[-line_limit:]
    return {
        "line_count": len(lines),
        "returned_line_count": len(selected),
        "truncated_from_start": line_limit >= 0 and len(lines) > len(selected),
        "text": "\n".join(selected),
    }

async def get_mcp_addon_info(
    addon_slug: Optional[str] = None,
    include_logs: bool = False,
    log_lines: int = 200
) -> Dict[str, Any]:
    """Read Supervisor information for the MCP add-on."""
    require_ha_cli_enabled()
    slug = addon_slug or MCP_ADDON_SLUG
    supervisor_api = SupervisorAPI()

    result = {
        "addon_slug": slug,
        "runtime": get_mcp_runtime_status(),
        "info": await supervisor_api.get_addon_info(slug),
    }

    try:
        result["stats"] = await supervisor_api.get_addon_stats(slug)
    except Exception as exc:
        result["stats_error"] = str(exc)

    if include_logs:
        logs = await supervisor_api.get_addon_logs(slug)
        result["logs"] = _tail_text_lines(logs, log_lines)

    return result

async def get_mcp_addon_logs(addon_slug: Optional[str] = None, lines: int = 200) -> Dict[str, Any]:
    """Read logs for the MCP add-on."""
    require_ha_cli_enabled()
    slug = addon_slug or MCP_ADDON_SLUG
    supervisor_api = SupervisorAPI()
    logs = await supervisor_api.get_addon_logs(slug)
    return {
        "addon_slug": slug,
        "logs": _tail_text_lines(logs, lines),
        "timestamp": datetime.now().astimezone().isoformat(),
    }

async def restart_mcp_addon(addon_slug: Optional[str] = None) -> Dict[str, Any]:
    """Restart the MCP add-on through Supervisor."""
    require_ha_write_allowed()
    slug = addon_slug or MCP_ADDON_SLUG
    supervisor_api = SupervisorAPI()
    return await supervisor_api.addon_action(slug, "restart")

async def get_ha_entities_and_devices(
    limit: Optional[int] = None,
    offset: int = 0,
    entity_filter: Optional[str] = None,
    domain_filter: Optional[str] = None,
    include_entities: bool = True,
    include_devices: bool = True,
    include_services: bool = False
) -> Dict[str, Any]:
    """Get entities and devices from Home Assistant via REST API with filtering and pagination."""
    
    if not ENABLE_HA_CLI:
        raise Exception("HA CLI commands are disabled")
    
    supervisor_token = os.getenv("SUPERVISOR_TOKEN")
    if not supervisor_token:
        raise Exception("SUPERVISOR_TOKEN not available")
    
    supervisor_api = SupervisorAPI()
    
    try:
        result = {
            "summary": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # Get entities if requested
        if include_entities:
            entities_data = await supervisor_api.get_ha_entities()
            all_entities = entities_data.get("entities", [])
            
            # Apply domain filter
            if domain_filter:
                all_entities = [e for e in all_entities if e.get("entity_id", "").startswith(f"{domain_filter}.")]
            
            # Apply entity_id filter (search pattern on entity_id and friendly_name)
            if entity_filter:
                all_entities = [
                    e for e in all_entities 
                    if entity_filter.lower() in e.get("entity_id", "").lower() or 
                       entity_filter.lower() in e.get("attributes", {}).get("friendly_name", "").lower()
                ]
            
            # Apply pagination
            total_entities = len(all_entities)
            start_idx = offset
            end_idx = offset + limit if limit else len(all_entities)
            paginated_entities = all_entities[start_idx:end_idx]
            
            result["entities"] = {
                "items": paginated_entities,
                "total_count": total_entities,
                "returned_count": len(paginated_entities),
                "offset": offset,
                "limit": limit
            }
            result["summary"]["entity_count"] = total_entities
        
        # Get devices if requested
        if include_devices:
            try:
                devices_data = await supervisor_api.get_ha_devices()
                all_devices = devices_data.get("devices", [])
                
                # Apply pagination
                total_devices = len(all_devices)
                start_idx = offset
                end_idx = offset + limit if limit else len(all_devices)
                paginated_devices = all_devices[start_idx:end_idx]
                
                result["devices"] = {
                    "items": paginated_devices,
                    "total_count": total_devices,
                    "returned_count": len(paginated_devices),
                    "offset": offset,
                    "limit": limit
                }
                result["summary"]["device_count"] = total_devices
            except Exception as device_error:
                logger.warning(f"Could not get devices: {device_error}")
                result["devices"] = {
                    "items": [],
                    "total_count": 0,
                    "error": "Device registry access may require additional permissions"
                }
                result["summary"]["device_count"] = 0
        
        # Get services if requested
        if include_services:
            try:
                services_data = await supervisor_api.get_ha_services()
                result["services"] = services_data
                result["summary"]["service_domains"] = len(services_data.get("services", {}))
            except Exception as service_error:
                logger.warning(f"Could not get services: {service_error}")
                result["services"] = {
                    "services": {},
                    "error": str(service_error)
                }
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting HA entities/devices: {e}")
        raise Exception(f"Failed to get entities/devices: {str(e)}")

async def mqtt_publish(topic: str, payload: str, broker: str = None, port: int = None, 
                      username: str = None, password: str = None, qos: int = 0, 
                      retain: bool = False) -> Dict[str, Any]:
    """Publish a message to an MQTT topic."""
    broker = broker or MQTT_BROKER
    port = port or MQTT_PORT
    username = username or MQTT_USERNAME
    password = password or MQTT_PASSWORD
    
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        
        if username:
            client.username_pw_set(username, password)
        
        # Connect to broker
        client.connect(broker, port, 60)
        
        # Publish message
        result = client.publish(topic, payload, qos=qos, retain=retain)
        
        # Wait for publish to complete
        result.wait_for_publish(timeout=5)
        
        client.disconnect()
        
        return {
            "success": True,
            "broker": broker,
            "port": port,
            "topic": topic,
            "payload": payload,
            "qos": qos,
            "retain": retain,
            "message": "Message published successfully"
        }
        
    except Exception as e:
        logger.error(f"Error publishing to MQTT topic '{topic}': {e}")
        raise Exception(f"Failed to publish MQTT message: {str(e)}")


async def mqtt_subscribe(topic: str, broker: str = None, port: int = None,
                        username: str = None, password: str = None, 
                        timeout: int = 10, max_messages: int = 10) -> Dict[str, Any]:
    """Subscribe to an MQTT topic and collect messages."""
    broker = broker or MQTT_BROKER
    port = port or MQTT_PORT
    username = username or MQTT_USERNAME
    password = password or MQTT_PASSWORD
    
    messages = []
    
    def on_connect(client, userdata, flags, reason_code, properties):
        client.subscribe(topic)
        logger.info(f"Subscribed to topic: {topic}")
    
    def on_message(client, userdata, msg):
        messages.append({
            "topic": msg.topic,
            "payload": msg.payload.decode('utf-8', errors='replace'),
            "qos": msg.qos,
            "retain": msg.retain,
            "timestamp": datetime.now().isoformat()
        })
        if len(messages) >= max_messages:
            client.disconnect()
    
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_message = on_message
        
        if username:
            client.username_pw_set(username, password)
        
        # Connect to broker
        client.connect(broker, port, 60)
        
        # Start loop in background
        client.loop_start()
        
        # Wait for messages or timeout
        start_time = time.time()
        while time.time() - start_time < timeout and len(messages) < max_messages:
            await asyncio.sleep(0.1)
        
        client.loop_stop()
        client.disconnect()
        
        return {
            "success": True,
            "broker": broker,
            "port": port,
            "topic": topic,
            "messages_received": len(messages),
            "messages": messages,
            "timeout_reached": time.time() - start_time >= timeout
        }
        
    except Exception as e:
        logger.error(f"Error subscribing to MQTT topic '{topic}': {e}")
        raise Exception(f"Failed to subscribe to MQTT topic: {str(e)}")


def parse_ha_cli_argv(command: str) -> List[str]:
    """Parse only the exact, read-only CLI forms implemented by SupervisorAPI."""
    if not isinstance(command, str) or not command.strip() or len(command) > 512:
        raise BackupValidationError("HA CLI command must be a non-empty string of at most 512 characters")
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise BackupValidationError("HA CLI command contains invalid quoting") from exc

    exact_forms = {
        ("ha", "addons"),
        ("ha", "supervisor", "logs"),
        ("ha", "core", "logs"),
        ("ha", "host", "logs"),
    }
    if tuple(argv) in exact_forms:
        return argv
    if len(argv) == 4 and argv[:3] in (["ha", "addons", "logs"], ["ha", "addons", "info"]):
        validate_backup_slug(argv[3])
        return argv
    if argv in (["ha", "backups"], ["ha", "backups", "list"]):
        require_backup_access()
        return argv
    if len(argv) == 4 and argv[:3] == ["ha", "backups", "info"]:
        require_backup_access()
        validate_backup_slug(argv[3])
        return argv
    raise PermissionError("HA CLI command is not one of the exact read-only allowlisted forms")

async def execute_ha_cli_command(command: str, timeout: int = 30) -> Dict[str, Any]:
    """Execute a strictly parsed HA CLI command without invoking a shell."""
    require_ha_cli_enabled()
    argv = parse_ha_cli_argv(command)
    timeout = _bounded_backup_int("timeout", timeout, 1, 30)
    normalized_command = shlex.join(argv)
    try:
        if argv[1] == "backups":
            payload = (
                await get_ha_backup_info(argv[3])
                if len(argv) == 4
                else await list_ha_backups()
            )
            return {
                "command": normalized_command,
                "return_code": 0,
                "stdout": json.dumps(payload, indent=2),
                "stderr": "",
                "success": True,
            }

        if os.getenv("SUPERVISOR_TOKEN"):
            return await SupervisorAPI().execute_ha_cli_equivalent(normalized_command)

        logger.warning("SUPERVISOR_TOKEN not found; using strict non-shell HA CLI execution")
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise TimeoutError(f"Command timed out after {timeout} seconds")

        output_limit = 1024 * 1024
        stdout_truncated = len(stdout) > output_limit
        stderr_truncated = len(stderr) > output_limit
        return {
            "command": normalized_command,
            "return_code": process.returncode,
            "stdout": stdout[:output_limit].decode("utf-8", errors="replace"),
            "stderr": stderr[:output_limit].decode("utf-8", errors="replace"),
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "success": process.returncode == 0,
        }
    except Exception as exc:
        logger.error("Safe HA CLI execution failed: %s", redact_sensitive_text(exc))
        raise RuntimeError(f"Failed to execute command: {redact_sensitive_text(exc)}") from exc

async def handle_mcp_request(request: JsonRpcRequest) -> JsonRpcResponse:
    """Handle MCP JSON-RPC requests according to the Azure Functions pattern."""
    
    try:
        if request.method == "initialize":
            return JsonRpcResponse(
                id=request.id,
                result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "ha-mcp-file-server",
                        "version": VERSION
                    }
                }
            )
        
        elif request.method == "tools/list":
            tools = [
                {
                    "name": "list_directory",
                    "description": "List files and directories in a path",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory path to list"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "read_file",
                    "description": "Read contents of a file",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to read"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "write_file",
                    "description": "Write content to a file",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to write"},
                            "content": {"type": "string", "description": "Content to write"}
                        },
                        "required": ["path", "content"]
                    }
                },
                {
                    "name": "create_directory",
                    "description": "Create a new directory",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory path to create"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "delete_path",
                    "description": "Delete a file or directory",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path to delete"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "search_files",
                    "description": "Search for files containing specific text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory to search in"},
                            "pattern": {"type": "string", "description": "Text pattern to search for"}
                        },
                        "required": ["path", "pattern"]
                    }
                },
                {
                    "name": "read_file_filtered",
                    "description": "Read file with filtering support for large files",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to read"},
                            "filter_pattern": {"type": "string", "description": "Text pattern to filter lines (case-insensitive)"},
                            "tail_lines": {"type": "integer", "description": "Number of lines from end of file to process"},
                            "max_lines": {"type": "integer", "description": "Maximum number of lines to return (default: 1000)"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "query_logs",
                    "description": "Query Home Assistant log files from the tail with time, level, logger, and text filters.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Log file path. Default: /config/home-assistant.log", "default": "/config/home-assistant.log"},
                            "since": {"type": "string", "description": "Start time as ISO timestamp or relative time like -30m, -90m, -2h, -7d"},
                            "level": {
                                "description": "Log level or levels to include, e.g. ERROR or ['WARNING','ERROR']",
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}}
                                ]
                            },
                            "logger_filter": {
                                "description": "Logger substring or substrings to match",
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}}
                                ]
                            },
                            "text_filter": {
                                "description": "Message text pattern or patterns to match",
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "array", "items": {"type": "string"}}
                                ]
                            },
                            "match_mode": {"type": "string", "description": "Pattern matching mode: any or all", "default": "any"},
                            "limit": {"type": "integer", "description": "Maximum records to return", "default": 200},
                            "max_bytes": {"type": "integer", "description": "Maximum bytes to read from the end of the log", "default": 2097152}
                        },
                        "required": []
                    }
                },
                {
                    "name": "get_mcp_runtime_status",
                    "description": "Show the effective MCP server runtime configuration, including whether MCP_ENABLE_HA_CLI is active.",
                    "inputSchema": {"type": "object", "properties": {}, "required": []}
                },
                {
                    "name": "validate_yaml_file",
                    "description": "Validate a YAML file with duplicate-key detection and warnings for ambiguous plain scalars like on/off/yes/no.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "YAML file path to validate"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "validate_automation_file",
                    "description": "Validate a Home Assistant automation YAML file and optionally run Home Assistant's full config check.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Automation YAML file path to validate"},
                            "run_check_config": {"type": "boolean", "description": "Also run Home Assistant check_config after local validation", "default": False}
                        },
                        "required": ["path"]
                    }
                }
            ]
            
            # Add HA CLI tools if enabled
            if ENABLE_HA_CLI:
                tools.extend([
                    {
                        "name": "execute_ha_cli",
                        "description": "Execute Home Assistant CLI commands safely (requires MCP_ENABLE_HA_CLI=true)",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "HA CLI command to execute (e.g., 'ha addons logs core_matter_server')"},
                                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)", "default": 30}
                            },
                            "required": ["command"]
                        }
                    },
                    {
                        "name": "list_ha_entities_devices",
                        "description": "List Home Assistant entities, devices, and services via REST API with pagination and filtering (requires MCP_ENABLE_HA_CLI=true). Use limit parameter to control response size.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "limit": {
                                    "type": "integer",
                                    "description": "Maximum number of items to return (default: 50, recommended: 10-100 for large systems)",
                                    "default": 50
                                },
                                "offset": {
                                    "type": "integer",
                                    "description": "Number of items to skip for pagination (default: 0)",
                                    "default": 0
                                },
                                "domain_filter": {
                                    "type": "string",
                                    "description": "Filter entities by domain (e.g., 'light', 'sensor', 'switch', 'climate')"
                                },
                                "entity_filter": {
                                    "type": "string",
                                    "description": "Search pattern to filter entity IDs and friendly names (case-insensitive substring match)"
                                },
                                "include_entities": {
                                    "type": "boolean",
                                    "description": "Include entities in response (default: true)",
                                    "default": True
                                },
                                "include_devices": {
                                    "type": "boolean",
                                    "description": "Include devices in response (default: true)",
                                    "default": True
                                },
                                "include_services": {
                                    "type": "boolean",
                                    "description": "Include services in response (default: false)",
                                    "default": False
                                }
                            },
                            "required": []
                        }
                    },
                    {
                        "name": "get_ha_entity_registry",
                        "description": "Get entities from Home Assistant entity registry with pagination (requires MCP_ENABLE_HA_CLI=true). This is the most efficient way to get entities with platform information (mqtt, zwave, etc.), unique_id, and registry metadata. Use limit parameter to control response size. Default limit is 100 entities. Use fields parameter to reduce token usage by returning only specific fields.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "limit": {
                                    "type": "integer",
                                    "description": "Maximum number of entities to return (default: 100, set to 0 for count only)",
                                    "default": 100
                                },
                                "offset": {
                                    "type": "integer",
                                    "description": "Number of entities to skip for pagination (default: 0)",
                                    "default": 0
                                },
                                "platform_filter": {
                                    "type": "string",
                                    "description": "Filter entities by platform (e.g., 'mqtt', 'zwave', 'zigbee', 'esphome')"
                                },
                                "entity_filter": {
                                    "type": "string",
                                    "description": "Search pattern to filter entity IDs (case-insensitive substring match)"
                                },
                                "fields": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "List of field names to return. If not specified, returns all fields. Common fields: 'entity_id', 'unique_id', 'platform', 'original_name', 'device_id'. Use this to reduce token usage (e.g., ['entity_id', 'unique_id'] reduces tokens by ~95%)."
                                }
                            },
                            "required": []
                        }
                    },
                    {
                        "name": "get_ha_entity_history",
                        "description": "Get historical state changes for Home Assistant entities (requires MCP_ENABLE_HA_CLI=true). Essential for analyzing heating systems, HVAC performance, automation debugging, and system optimization. Returns state changes with timestamps, statistical analysis for numeric sensors, and performance metrics.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "entity_id": {
                                    "type": "string",
                                    "description": "Target entity ID (e.g., 'sensor.diyless_thermostat_1_ch_temperature', 'binary_sensor.flame_sensor')"
                                },
                                "start_time": {
                                    "type": "string",
                                    "description": "Start time in ISO 8601 format or relative format ('-30m', '-90m', '-6h', '-24h', '-7d'). Default: 12 hours ago"
                                },
                                "end_time": {
                                    "type": "string",
                                    "description": "End time in ISO 8601 format or 'now'. Default: current time"
                                },
                                "limit": {
                                    "type": "integer",
                                    "description": "Maximum number of state changes to return. Default: 1000",
                                    "default": 1000
                                },
                                "minimal_change": {
                                    "type": "number",
                                    "description": "For numeric sensors, filter out changes smaller than this value (e.g., 0.1 for temperature sensors to reduce noise)"
                                },
                                "unavailable_transitions_only": {
                                    "type": "boolean",
                                    "description": "Only return transitions to or from unavailable",
                                    "default": False
                                }
                            },
                        "required": ["entity_id"]
                    }
                },
                {
                    "name": "get_ha_entities_history",
                    "description": "Get historical summaries for multiple Home Assistant entities in one request, including statistics, unavailable periods, and an optional combined timeline.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "entity_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Entity IDs to fetch history for"
                            },
                            "start_time": {
                                "type": "string",
                                "description": "Start time in ISO 8601 format or relative format like -30m, -90m, -6h, -24h, -7d. Default: 12 hours ago"
                            },
                            "end_time": {
                                "type": "string",
                                "description": "End time in ISO 8601 format or now. Default: current time"
                            },
                            "limit_per_entity": {
                                "type": "integer",
                                "description": "Maximum state changes to return per entity",
                                "default": 1000
                            },
                            "minimal_change": {
                                "type": "number",
                                "description": "For numeric sensors, filter out changes smaller than this value"
                            },
                            "unavailable_transitions_only": {
                                "type": "boolean",
                                "description": "Only include transitions to or from unavailable in returned changes and timeline",
                                "default": False
                            },
                            "include_state_changes": {
                                "type": "boolean",
                                "description": "Include per-entity state_changes arrays. Disabled by default to keep responses compact.",
                                "default": False
                            },
                            "include_timeline": {
                                "type": "boolean",
                                "description": "Include a combined cross-entity timeline",
                                "default": True
                            },
                            "timeline_limit": {
                                "type": "integer",
                                "description": "Maximum combined timeline items to return",
                                "default": 1000
                            }
                        },
                        "required": ["entity_ids"]
                    }
                },
                {
                    "name": "get_states",
                    "description": "Get a compact current-state snapshot for multiple Home Assistant entities in one API call.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "entity_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Entity IDs to fetch"
                            },
                            "attributes": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional attribute names to include. If omitted, all attributes are returned."
                            }
                        },
                        "required": ["entity_ids"]
                    }
                },
                {
                    "name": "get_mcp_addon_info",
                    "description": "Get Supervisor info, options/config, runtime flags, and optional logs for the MCP add-on.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "addon_slug": {"type": "string", "description": "Add-on slug. Default: local_mcp_file_server"},
                            "include_logs": {"type": "boolean", "description": "Include recent add-on logs", "default": False},
                            "log_lines": {"type": "integer", "description": "Number of log lines to return when include_logs=true", "default": 200}
                        },
                        "required": []
                    }
                },
                {
                    "name": "get_mcp_addon_logs",
                    "description": "Get recent logs for the MCP add-on.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "addon_slug": {"type": "string", "description": "Add-on slug. Default: local_mcp_file_server"},
                            "lines": {"type": "integer", "description": "Number of log lines to return", "default": 200}
                        },
                        "required": []
                    }
                },
                {
                    "name": "restart_mcp_addon",
                    "description": "Restart the MCP add-on through Supervisor. Requires enable_ha_cli=true and read_only=false.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "addon_slug": {"type": "string", "description": "Add-on slug. Default: local_mcp_file_server"}
                        },
                        "required": []
                    }
                },
                {
                    "name": "call_service",
                    "description": "Call an allowlisted Home Assistant service through the WebSocket API. Blocked when read_only=true.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "domain": {"type": "string", "description": "Service domain, e.g. automation, number, select"},
                            "service": {"type": "string", "description": "Service name, e.g. reload, set_value, select_option"},
                            "target": {"type": "object", "description": "Home Assistant service target", "default": {}},
                            "data": {"type": "object", "description": "Home Assistant service data", "default": {}},
                            "return_response": {"type": "boolean", "description": "Request a service response from Home Assistant", "default": False}
                        },
                        "required": ["domain", "service"]
                    }
                },
                {
                    "name": "reload_automations",
                    "description": "Reload Home Assistant automations, optionally one automation id.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "automation_id": {"type": "string", "description": "Optional automation id to reload"}
                        },
                        "required": []
                    }
                },
                {
                    "name": "reload_scripts",
                    "description": "Reload Home Assistant scripts.",
                    "inputSchema": {"type": "object", "properties": {}, "required": []}
                },
                {
                    "name": "reload_template_entities",
                    "description": "Reload Home Assistant template entities.",
                    "inputSchema": {"type": "object", "properties": {}, "required": []}
                },
                {
                    "name": "reload_python_scripts",
                    "description": "Reload Home Assistant python_scripts.",
                    "inputSchema": {"type": "object", "properties": {}, "required": []}
                },
                {
                    "name": "reload_integration",
                    "description": "Reload a Home Assistant config entry by entry_id.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "entry_id": {"type": "string", "description": "Home Assistant config entry id"}
                        },
                        "required": ["entry_id"]
                    }
                },
                {
                    "name": "check_config",
                    "description": "Run Home Assistant's core config check.",
                    "inputSchema": {"type": "object", "properties": {}, "required": []}
                },
                {
                    "name": "get_automation_trace",
                    "description": "Read recent Home Assistant automation traces and return a compact debugging summary.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "entity_id": {"type": "string", "description": "Automation entity id, e.g. automation.my_automation"},
                            "last_n": {"type": "integer", "description": "Number of recent traces to fetch", "default": 5},
                            "include_raw": {"type": "boolean", "description": "Include raw Home Assistant trace payloads", "default": False}
                        },
                        "required": ["entity_id"]
                    }
                }
                ])

            # Backup tools are hidden unless all security prerequisites are active.
            if backup_access_ready():
                tools.extend([
                    {
                        "name": "list_ha_backups",
                        "description": "List bounded Home Assistant backup metadata. Requires explicit backup enablement and strong API-key authentication.",
                        "inputSchema": {"type": "object", "properties": {}, "required": []},
                    },
                    {
                        "name": "search_ha_backups",
                        "description": "Search text-like files in Home Assistant backups with strict download, archive, time and concurrency limits.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "patterns": {
                                    "oneOf": [
                                        {"type": "string", "maxLength": BACKUP_LIMITS.max_pattern_chars},
                                        {
                                            "type": "array",
                                            "items": {"type": "string", "maxLength": BACKUP_LIMITS.max_pattern_chars},
                                            "minItems": 1,
                                            "maxItems": BACKUP_LIMITS.max_patterns,
                                        },
                                    ]
                                },
                                "backup_slugs": {
                                    "type": "array",
                                    "items": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
                                    "maxItems": BACKUP_LIMITS.max_backups,
                                },
                                "max_backups": {"type": "integer", "minimum": 1, "maximum": BACKUP_LIMITS.max_backups, "default": 5},
                                "max_matches": {"type": "integer", "minimum": 1, "maximum": BACKUP_LIMITS.max_matches, "default": 100},
                                "match_mode": {"type": "string", "enum": ["any", "all"], "default": "any"},
                                "include_content": {"type": "boolean", "default": False},
                                "acknowledge_sensitive_content": {
                                    "type": "boolean",
                                    "description": "Must be true when include_content=true; returned snippets are still redacted.",
                                    "default": False,
                                },
                                "context_lines": {"type": "integer", "minimum": 0, "maximum": BACKUP_LIMITS.max_context_lines, "default": 0},
                            },
                            "required": ["patterns"],
                        },
                    },
                ])
            
            # Add MQTT tools
            tools.extend([
                {
                    "name": "mqtt_publish",
                    "description": "Publish a message to an MQTT topic. Default broker: 192.168.1.78, no authentication required by default.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "description": "MQTT topic to publish to (e.g., 'home/livingroom/light')"},
                            "payload": {"type": "string", "description": "Message payload to publish"},
                            "broker": {"type": "string", "description": "MQTT broker IP address (default: 192.168.1.78)"},
                            "port": {"type": "integer", "description": "MQTT broker port (default: 1883)"},
                            "username": {"type": "string", "description": "MQTT username (optional)"},
                            "password": {"type": "string", "description": "MQTT password (optional)"},
                            "qos": {"type": "integer", "description": "Quality of Service level (0, 1, or 2, default: 0)", "default": 0},
                            "retain": {"type": "boolean", "description": "Retain message flag (default: false)", "default": False}
                        },
                        "required": ["topic", "payload"]
                    }
                },
                {
                    "name": "mqtt_subscribe",
                    "description": "Subscribe to an MQTT topic and collect messages. Default broker: 192.168.1.78, no authentication required by default.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "description": "MQTT topic to subscribe to (supports wildcards like 'home/#' or 'home/+/temperature')"},
                            "broker": {"type": "string", "description": "MQTT broker IP address (default: 192.168.1.78)"},
                            "port": {"type": "integer", "description": "MQTT broker port (default: 1883)"},
                            "username": {"type": "string", "description": "MQTT username (optional)"},
                            "password": {"type": "string", "description": "MQTT password (optional)"},
                            "timeout": {"type": "integer", "description": "Maximum time to wait for messages in seconds (default: 10)", "default": 10},
                            "max_messages": {"type": "integer", "description": "Maximum number of messages to collect (default: 10)", "default": 10}
                        },
                        "required": ["topic"]
                    }
                }
            ])
            
            return JsonRpcResponse(
                id=request.id,
                result={"tools": tools}
            )
        
        elif request.method == "tools/call":
            tool_name = request.params.get("name")
            arguments = request.params.get("arguments", {})
            
            if tool_name == "list_directory":
                items = await file_handler.list_directory(arguments["path"])
                result = {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}
                
            elif tool_name == "read_file":
                content = await file_handler.read_file(arguments["path"])
                result = {"content": [{"type": "text", "text": content}]}
                
            elif tool_name == "write_file":
                if READ_ONLY:
                    raise Exception("Server is in read-only mode")
                await file_handler.write_file(arguments["path"], arguments["content"])
                result = {"content": [{"type": "text", "text": f"File written successfully: {arguments['path']}"}]}
                
            elif tool_name == "create_directory":
                if READ_ONLY:
                    raise Exception("Server is in read-only mode")
                await file_handler.create_directory(arguments["path"])
                result = {"content": [{"type": "text", "text": f"Directory created: {arguments['path']}"}]}
                
            elif tool_name == "delete_path":
                if READ_ONLY:
                    raise Exception("Server is in read-only mode")
                await file_handler.delete_path(arguments["path"])
                result = {"content": [{"type": "text", "text": f"Path deleted: {arguments['path']}"}]}
                
            elif tool_name == "search_files":
                results = await file_handler.search_files(arguments["path"], arguments["pattern"])
                result = {"content": [{"type": "text", "text": json.dumps(results, indent=2)}]}
                
            elif tool_name == "read_file_filtered":
                results = await file_handler.read_file_filtered(
                    arguments["path"],
                    filter_pattern=arguments.get("filter_pattern"),
                    tail_lines=arguments.get("tail_lines"),
                    max_lines=arguments.get("max_lines", 1000)
                )
                result = _json_text_result(results)

            elif tool_name == "query_logs":
                log_results = await query_logs(
                    path=arguments.get("path", "/config/home-assistant.log"),
                    since=arguments.get("since"),
                    level=arguments.get("level"),
                    logger_filter=arguments.get("logger_filter"),
                    text_filter=arguments.get("text_filter"),
                    limit=arguments.get("limit", 200),
                    max_bytes=arguments.get("max_bytes", 2 * 1024 * 1024),
                    match_mode=arguments.get("match_mode", "any")
                )
                result = _json_text_result(log_results)

            elif tool_name == "get_mcp_runtime_status":
                result = _json_text_result(get_mcp_runtime_status())

            elif tool_name == "validate_yaml_file":
                validation_result = await yaml_validator.validate_yaml_file(arguments["path"])
                validation_result.pop("parsed", None)
                result = _json_text_result(validation_result)

            elif tool_name == "validate_automation_file":
                validation_result = await yaml_validator.validate_automation_file(arguments["path"])
                if arguments.get("run_check_config"):
                    require_ha_cli_enabled()
                    supervisor_api = SupervisorAPI()
                    validation_result["check_config"] = await supervisor_api.check_config()
                result = _json_text_result(validation_result)
                
            elif tool_name == "execute_ha_cli":
                if not ENABLE_HA_CLI:
                    raise Exception("HA CLI commands are disabled. Set MCP_ENABLE_HA_CLI=true to enable.")
                
                command_result = await execute_ha_cli_command(
                    arguments["command"],
                    timeout=arguments.get("timeout", 30)
                )
                result = {"content": [{"type": "text", "text": json.dumps(command_result, indent=2)}]}

            elif tool_name == "list_ha_backups":
                result = _json_text_result(await list_ha_backups())

            elif tool_name == "search_ha_backups":
                result = _json_text_result(await search_ha_backups(
                    patterns=arguments["patterns"],
                    backup_slugs=arguments.get("backup_slugs"),
                    max_backups=arguments.get("max_backups", 5),
                    max_matches=arguments.get("max_matches", 100),
                    include_content=arguments.get("include_content", False),
                    acknowledge_sensitive_content=arguments.get("acknowledge_sensitive_content", False),
                    context_lines=arguments.get("context_lines", 0),
                    match_mode=arguments.get("match_mode", "any"),
                ))
                
            elif tool_name == "list_ha_entities_devices":
                if not ENABLE_HA_CLI:
                    raise Exception("HA CLI commands are disabled. Set MCP_ENABLE_HA_CLI=true to enable.")
                
                ha_data = await get_ha_entities_and_devices(
                    limit=arguments.get("limit", 50),
                    offset=arguments.get("offset", 0),
                    entity_filter=arguments.get("entity_filter"),
                    domain_filter=arguments.get("domain_filter"),
                    include_entities=arguments.get("include_entities", True),
                    include_devices=arguments.get("include_devices", True),
                    include_services=arguments.get("include_services", False)
                )
                result = {"content": [{"type": "text", "text": json.dumps(ha_data, indent=2)}]}
            
            elif tool_name == "get_ha_entity_registry":
                if not ENABLE_HA_CLI:
                    raise Exception("HA CLI commands are disabled. Set MCP_ENABLE_HA_CLI=true to enable.")
                
                supervisor_api = SupervisorAPI()
                registry_data = await supervisor_api.get_ha_entity_registry()
                
                # Apply filters if provided
                all_entities = registry_data.get("entities", [])
                total_count = len(all_entities)
                
                # Filter by platform
                platform_filter = arguments.get("platform_filter")
                if platform_filter:
                    all_entities = [e for e in all_entities if e.get("platform", "").lower() == platform_filter.lower()]
                
                # Filter by entity_id pattern
                entity_filter = arguments.get("entity_filter")
                if entity_filter:
                    all_entities = [e for e in all_entities if entity_filter.lower() in e.get("entity_id", "").lower()]
                
                # Get pagination parameters
                limit = arguments.get("limit", 100)
                offset = arguments.get("offset", 0)
                
                # Apply pagination
                filtered_count = len(all_entities)
                start_idx = offset
                end_idx = offset + limit if limit > 0 else len(all_entities)
                paginated_entities = all_entities[start_idx:end_idx]
                
                # Apply field filtering if specified
                fields = arguments.get("fields")
                if fields and isinstance(fields, list):
                    paginated_entities = [
                        {key: entity.get(key) for key in fields if key in entity}
                        for entity in paginated_entities
                    ]
                
                # Prepare response with filtered and paginated data
                filtered_result = {
                    "entities": paginated_entities,
                    "pagination": {
                        "returned_count": len(paginated_entities),
                        "filtered_count": filtered_count,
                        "total_count": total_count,
                        "offset": offset,
                        "limit": limit
                    },
                    "timestamp": registry_data.get("timestamp"),
                    "filters_applied": {
                        "platform": platform_filter,
                        "entity_pattern": entity_filter,
                        "fields": fields if fields else "all"
                    }
                }
                
                # Include fallback info if present
                if registry_data.get("fallback_mode"):
                    filtered_result["fallback_mode"] = True
                    filtered_result["note"] = registry_data.get("note")
                
                result = {"content": [{"type": "text", "text": json.dumps(filtered_result, indent=2)}]}
            
            elif tool_name == "get_ha_entity_history":
                if not ENABLE_HA_CLI:
                    raise Exception("HA CLI commands are disabled. Set MCP_ENABLE_HA_CLI=true to enable.")
                
                supervisor_api = SupervisorAPI()
                history_data = await supervisor_api.get_ha_entity_history(
                    entity_id=arguments["entity_id"],
                    start_time=arguments.get("start_time"),
                    end_time=arguments.get("end_time"),
                    limit=arguments.get("limit", 1000),
                    minimal_change=arguments.get("minimal_change"),
                    unavailable_transitions_only=arguments.get("unavailable_transitions_only", False)
                )
                result = _json_text_result(history_data)

            elif tool_name == "get_ha_entities_history":
                require_ha_cli_enabled()
                supervisor_api = SupervisorAPI()
                history_data = await supervisor_api.get_ha_entities_history(
                    entity_ids=arguments["entity_ids"],
                    start_time=arguments.get("start_time"),
                    end_time=arguments.get("end_time"),
                    limit_per_entity=arguments.get("limit_per_entity", 1000),
                    minimal_change=arguments.get("minimal_change"),
                    unavailable_transitions_only=arguments.get("unavailable_transitions_only", False),
                    include_state_changes=arguments.get("include_state_changes", False),
                    include_timeline=arguments.get("include_timeline", True),
                    timeline_limit=arguments.get("timeline_limit", 1000)
                )
                result = _json_text_result(history_data)

            elif tool_name == "get_states":
                require_ha_cli_enabled()
                supervisor_api = SupervisorAPI()
                states_data = await supervisor_api.get_states(
                    entity_ids=arguments["entity_ids"],
                    attributes=arguments.get("attributes")
                )
                result = _json_text_result(states_data)

            elif tool_name == "get_mcp_addon_info":
                addon_info = await get_mcp_addon_info(
                    addon_slug=arguments.get("addon_slug"),
                    include_logs=arguments.get("include_logs", False),
                    log_lines=arguments.get("log_lines", 200)
                )
                result = _json_text_result(addon_info)

            elif tool_name == "get_mcp_addon_logs":
                addon_logs = await get_mcp_addon_logs(
                    addon_slug=arguments.get("addon_slug"),
                    lines=arguments.get("lines", 200)
                )
                result = _json_text_result(addon_logs)

            elif tool_name == "restart_mcp_addon":
                restart_result = await restart_mcp_addon(
                    addon_slug=arguments.get("addon_slug")
                )
                result = _json_text_result(restart_result)

            elif tool_name == "call_service":
                service_result = await call_allowed_service(
                    domain=arguments["domain"],
                    service=arguments["service"],
                    target=arguments.get("target", {}),
                    data=arguments.get("data", {}),
                    return_response=arguments.get("return_response", False)
                )
                result = _json_text_result(service_result)

            elif tool_name == "reload_automations":
                data = {}
                if arguments.get("automation_id"):
                    data["id"] = arguments["automation_id"]
                service_result = await call_allowed_service("automation", "reload", data=data)
                result = _json_text_result(service_result)

            elif tool_name == "reload_scripts":
                service_result = await call_allowed_service("script", "reload")
                result = _json_text_result(service_result)

            elif tool_name == "reload_template_entities":
                service_result = await call_allowed_service("template", "reload")
                result = _json_text_result(service_result)

            elif tool_name == "reload_python_scripts":
                service_result = await call_allowed_service("python_script", "reload")
                result = _json_text_result(service_result)

            elif tool_name == "reload_integration":
                service_result = await call_allowed_service(
                    "homeassistant",
                    "reload_config_entry",
                    data={"entry_id": arguments["entry_id"]}
                )
                result = _json_text_result(service_result)

            elif tool_name == "check_config":
                require_ha_cli_enabled()
                supervisor_api = SupervisorAPI()
                result = _json_text_result(await supervisor_api.check_config())

            elif tool_name == "get_automation_trace":
                trace_result = await get_automation_trace_summary(
                    entity_id=arguments["entity_id"],
                    last_n=arguments.get("last_n", 5),
                    include_raw=arguments.get("include_raw", False)
                )
                result = _json_text_result(trace_result)
            
            elif tool_name == "mqtt_publish":
                mqtt_result = await mqtt_publish(
                    topic=arguments["topic"],
                    payload=arguments["payload"],
                    broker=arguments.get("broker"),
                    port=arguments.get("port"),
                    username=arguments.get("username"),
                    password=arguments.get("password"),
                    qos=arguments.get("qos", 0),
                    retain=arguments.get("retain", False)
                )
                result = {"content": [{"type": "text", "text": json.dumps(mqtt_result, indent=2)}]}
            
            elif tool_name == "mqtt_subscribe":
                mqtt_result = await mqtt_subscribe(
                    topic=arguments["topic"],
                    broker=arguments.get("broker"),
                    port=arguments.get("port"),
                    username=arguments.get("username"),
                    password=arguments.get("password"),
                    timeout=arguments.get("timeout", 10),
                    max_messages=arguments.get("max_messages", 10)
                )
                result = {"content": [{"type": "text", "text": json.dumps(mqtt_result, indent=2)}]}
                
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
            
            return JsonRpcResponse(id=request.id, result=result)
        
        else:
            return JsonRpcResponse(
                id=request.id,
                error={
                    "code": -32601,
                    "message": f"Method not found: {request.method}"
                }
            )
    
    except Exception as e:
        safe_error = redact_sensitive_text(e)
        logger.error("Error handling MCP request: %s", safe_error)
        return JsonRpcResponse(
            id=request.id,
            error={
                "code": -32603,
                "message": safe_error
            }
        )

# GET endpoint for MCP capability discovery.
@app.get("/api/mcp")
async def mcp_get_endpoint(
    x_mcp_api_key: Optional[str] = Header(default=None, alias="X-MCP-API-Key"),
):
    """Return server metadata after header-based authentication."""
    if API_KEY:
        verify_function_key(x_mcp_api_key)
    
    return {
        "name": "Home Assistant MCP File Server",
        "version": VERSION,
        "description": "File management server for Home Assistant",
        "protocol": "MCP 2024-11-05",
        "transport": "HTTP",
        "capabilities": ["tools"],
        "status": "healthy",
        "read_only": READ_ONLY,
        "allowed_dirs": ALLOWED_DIRS,
        "allowed_services": ALLOWED_SERVICES,
        "ha_cli_enabled": ENABLE_HA_CLI,
        "backup_inspection_enabled": ENABLE_BACKUP_INSPECTION,
        "backup_access_ready": backup_access_ready()
    }

# POST endpoint for MCP requests (like Azure Functions pattern)
@app.post("/api/mcp")
async def mcp_post_endpoint(
    request: Request,
    x_mcp_api_key: Optional[str] = Header(default=None, alias="X-MCP-API-Key"),
):
    """
    Main MCP endpoint following Azure Functions pattern.
    Handles all JSON-RPC 2.0 MCP protocol requests.
    """
    
    # Verify function key if configured
    if API_KEY:
        verify_function_key(x_mcp_api_key)
    
    try:
        # Parse JSON-RPC request
        body = await request.json()
        
        # Handle single request or batch
        if isinstance(body, list):
            # Batch request
            responses = []
            for req_data in body:
                req = JsonRpcRequest(**req_data)
                resp = await handle_mcp_request(req)
                responses.append(resp.model_dump(exclude_none=True))
            return responses
        else:
            # Single request
            req = JsonRpcRequest(**body)
            resp = await handle_mcp_request(req)
            return resp.model_dump(exclude_none=True)
    
    except Exception as e:
        logger.error(f"Error processing MCP request: {e}")
        return {
            "jsonrpc": "2.0",
            "error": {
                "code": -32700,
                "message": "Parse error"
            }
        }

# Health check endpoint (standard)
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": VERSION,
        "read_only": READ_ONLY,
        "allowed_dirs": ALLOWED_DIRS,
        "allowed_services": ALLOWED_SERVICES,
        "ha_cli_enabled": ENABLE_HA_CLI,
        "backup_inspection_enabled": ENABLE_BACKUP_INSPECTION,
        "backup_access_ready": backup_access_ready(),
        "mcp_endpoint": "/api/mcp"
    }

# CORS middleware
@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-MCP-API-Key"
    return response

@app.middleware("http")
async def reject_query_string_credentials(request: Request, call_next):
    """Reject the retired URL credential before it reaches an endpoint."""
    if "code" in request.query_params:
        return JSONResponse(
            status_code=400,
            content={"detail": "URL API keys are not supported; use X-MCP-API-Key"},
        )
    return await call_next(request)

if __name__ == "__main__":
    logger.info(f"Starting MCP File Server on port {PORT}")
    logger.info(f"MCP endpoint: http://0.0.0.0:{PORT}/api/mcp")
    logger.info(f"Read-only mode: {READ_ONLY}")
    logger.info(f"Allowed directories: {ALLOWED_DIRS}")
    logger.info(f"Allowed Home Assistant services: {ALLOWED_SERVICES}")
    logger.info(f"Function key configured: {'Yes' if API_KEY else 'No'}")
    logger.info(f"HA CLI enabled: {ENABLE_HA_CLI}")
    logger.info(f"Backup inspection enabled: {ENABLE_BACKUP_INSPECTION}")
    logger.info(f"Backup access safely configured: {backup_access_ready()}")
    
    # Do not emit raw request URLs: legacy clients may accidentally append a key.
    uvicorn.run(app, host="0.0.0.0", port=PORT, access_log=False)
