import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.constructor import DuplicateKeyError
    from ruamel.yaml.scanner import ScannerError
    from ruamel.yaml.parser import ParserError
    from ruamel.yaml.composer import ComposerError
except ImportError:
    YAML = None
    DuplicateKeyError = ScannerError = ParserError = ComposerError = tuple()


AMBIGUOUS_PLAIN_SCALARS = {"on", "off", "yes", "no", "true", "false"}


class YAMLValidator:
    """Validate YAML files inside the configured allowed directories."""

    def __init__(self, file_handler):
        self.file_handler = file_handler

    async def validate_yaml_file(self, path: str) -> Dict[str, Any]:
        file_path = self.file_handler._validate_path(path)
        content = await self.file_handler.read_file(path)
        return self.validate_yaml_content(content, file_path)

    def validate_yaml_content(self, content: str, file_path: Optional[Path] = None) -> Dict[str, Any]:
        result = {
            "valid": True,
            "path": str(file_path) if file_path else None,
            "errors": [],
            "warnings": [],
            "document_type": "yaml",
            "parsed_type": None,
        }

        if YAML is None:
            result["valid"] = False
            result["errors"].append({
                "type": "dependency_missing",
                "message": "ruamel.yaml is required for YAML validation.",
                "line": None,
                "column": None,
                "context": None,
            })
            result["parsed"] = None
            return result

        yaml = YAML(typ="rt")
        yaml.allow_duplicate_keys = False

        try:
            parsed = yaml.load(content) if content.strip() else None
            result["parsed_type"] = type(parsed).__name__ if parsed is not None else "NoneType"
        except DuplicateKeyError as exc:
            result["valid"] = False
            result["errors"].append(self._format_yaml_error("duplicate_key", exc))
            parsed = None
        except (ScannerError, ParserError, ComposerError) as exc:
            result["valid"] = False
            result["errors"].append(self._format_yaml_error("syntax", exc))
            parsed = None
        except Exception as exc:
            result["valid"] = False
            result["errors"].append({
                "type": "yaml_error",
                "message": str(exc),
                "line": None,
                "column": None,
                "context": None,
            })
            parsed = None

        result["warnings"].extend(self._find_ambiguous_plain_scalars(content))
        result["parsed"] = parsed
        return result

    async def validate_automation_file(self, path: str) -> Dict[str, Any]:
        result = await self.validate_yaml_file(path)
        parsed = result.pop("parsed", None)
        result["document_type"] = "automation"

        if not result["valid"]:
            return result

        automations = self._normalize_automations(parsed)
        if automations is None:
            result["valid"] = False
            result["errors"].append({
                "type": "automation_structure",
                "message": "Automation YAML must be a mapping or a list of mappings.",
                "line": None,
                "column": None,
                "context": None,
            })
            return result

        for index, automation in enumerate(automations):
            if not isinstance(automation, dict):
                result["valid"] = False
                result["errors"].append({
                    "type": "automation_structure",
                    "message": f"Automation at index {index} must be a mapping.",
                    "line": None,
                    "column": None,
                    "context": None,
                })
                continue

            for key in ("trigger", "action"):
                if key not in automation:
                    result["valid"] = False
                    result["errors"].append({
                        "type": "automation_structure",
                        "message": f"Automation at index {index} is missing required key '{key}'.",
                        "line": None,
                        "column": None,
                        "context": automation.get("id") or automation.get("alias"),
                    })

        result["automation_count"] = len(automations)
        return result

    def _normalize_automations(self, parsed: Any) -> Optional[List[Any]]:
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        return None

    def _format_yaml_error(self, error_type: str, exc: Exception) -> Dict[str, Any]:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        return {
            "type": error_type,
            "message": getattr(exc, "problem", str(exc)),
            "line": mark.line + 1 if mark else None,
            "column": mark.column + 1 if mark else None,
            "context": getattr(exc, "context", None),
        }

    def _find_ambiguous_plain_scalars(self, content: str) -> List[Dict[str, Any]]:
        warnings = []
        pattern = re.compile(r"^(\s*[^#:\n][^:\n]*:\s*)(on|off|yes|no|true|false)(\s*(?:#.*)?$)", re.IGNORECASE)

        for line_number, line in enumerate(content.splitlines(), 1):
            match = pattern.match(line)
            if not match:
                continue

            value = match.group(2)
            warnings.append({
                "type": "ambiguous_plain_scalar",
                "message": f"Plain scalar '{value}' may be interpreted as a boolean by Home Assistant/YAML tooling; quote it if it is meant as a string.",
                "line": line_number,
                "column": match.start(2) + 1,
                "value": value,
            })

        return warnings
