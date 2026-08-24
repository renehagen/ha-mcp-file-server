# CHANGELOG

## [1.6.0] - 2026-08-24

### Added
- Opt-in Home Assistant backup metadata listing and bounded archive search through Supervisor.
- Dedicated limits for downloads, total request bytes, archive members, unpacked bytes, nesting, patterns, matches, time, and concurrency.
- Negative and security tests for authentication, feature gates, content redaction, malformed archives, unsafe paths, limits, cleanup, and CLI injection attempts.

### Security
- Backup tools now require `enable_ha_cli`, explicit `enable_backup_inspection`, and an API key of at least 24 characters.
- `/backup` is not mounted or included in the general file-tool allowlist.
- `include_content=false` returns no snippets; explicitly enabled snippets are redacted.
- Archive scanning runs in a disposable worker process outside the async request loop, is terminated at the wall-clock limit, and never extracts archive member paths.
- The HA CLI dispatcher now validates exact argument vectors and uses no shell execution.
- API keys are accepted only through the `X-MCP-API-Key` header, never through URL query strings.
- Legacy `?code=` credentials are rejected and raw request-URL access logging is disabled.
- Backup CLI-compatible output is routed through the same bounded metadata sanitizer as the MCP backup tools.
- The hard backup-search deadline includes Supervisor listing and fallback calls.
- Content-return and acknowledgement flags require literal JSON booleans; truthy strings and numbers are rejected.
- Supervisor authentication headers and token prefixes are no longer logged.
- FastAPI, Starlette, Pydantic, multipart, and aiohttp were updated to versions without known advisories in the release audit.

### CI
- Added Python 3.12 tests, bytecode compilation, dependency auditing, and shell syntax validation.

## [1.5.0] - 2026-06-30

### Added
- **Log diagnostics** with `query_logs`, including tail reads, relative time windows, level filters, logger filters, text filters, and newest-first results.
- **Live state snapshots** with `get_states` for fetching multiple entity states in one Home Assistant REST call.
- **MCP add-on management** with `get_mcp_runtime_status`, `get_mcp_addon_info`, `get_mcp_addon_logs`, and `restart_mcp_addon`.
- **Multi-entity history summaries** with `get_ha_entities_history`, including numeric statistics, unavailable periods, and a combined timeline.
- **Minute-based relative history windows** such as `-30m` and `-90m`.
- **Unavailable transition filtering** for `get_ha_entity_history` with `unavailable_transitions_only=true`.
- `homeassistant.check_config` in the default service allowlist, alongside the richer `check_config` REST tool.
- Unit tests for batch 2 log querying, state snapshots, add-on management wrappers, multi-entity history, minute parsing, and unavailable transition filtering.

### Enhanced
- Entity history responses now include local timestamp fields, previous state, and Home Assistant context IDs where available.
- Log queries read only the requested tail bytes instead of scanning entire large log files.

## [1.4.0] - 2026-06-30

### Added
- **Allowlisted Home Assistant service calls** with new `call_service` tool using the HA WebSocket API and returning context IDs where available.
- **Reload tools** for automations, scripts, template entities, python scripts, and individual config entries.
- **Config and YAML validation** with `check_config`, `validate_yaml_file`, and `validate_automation_file`.
- **Automation trace inspection** with `get_automation_trace` for compact summaries of recent triggers, choices, variables, service calls, and errors.
- **Service allowlist configuration** through `allowed_services` / `MCP_ALLOWED_SERVICES`.
- Unit tests for allowlist enforcement, reload dispatch, YAML validation, and trace summarization.

### Security
- Home Assistant write/reload operations require `enable_ha_cli=true`, are blocked by `read_only=true`, and must match `allowed_services`.
- YAML validation remains available in read-only mode; `validate_automation_file(run_check_config=true)` requires HA tools to be enabled.

### Technical
- Added shared REST and WebSocket helpers in `SupervisorAPI`.
- Added `ruamel.yaml` for duplicate-key-aware YAML parsing and validation warnings for ambiguous plain scalars such as `off`.

## [1.3.0] - 2024-01-06

### Added
- **Historical Entity Data Analysis**: New `get_ha_entity_history` tool for comprehensive historical state analysis
  - Supports flexible time ranges (relative formats like "-6h", "-24h", "-7d" and ISO 8601 timestamps)  
  - Smart filtering with `minimal_change` parameter to reduce noise in sensor data
  - Automatic statistical analysis including min, max, average, and change frequency
  - Works with numeric sensors, binary sensors, and text-based entities
  - Optimized for HVAC analysis, automation debugging, and system monitoring
  - Comprehensive error handling for non-existent entities and API failures
- Example scripts and documentation in `/examples/` directory
  - `test_entity_history.py`: Test script for the new functionality
  - `ENTITY_HISTORY_EXAMPLES.md`: Comprehensive usage examples and patterns

### Enhanced
- Updated README.md with detailed documentation for historical analysis features
- Added comprehensive time format support and use case examples
- Improved feature descriptions to highlight HVAC optimization capabilities

### Technical
- Extended SupervisorAPI class with robust time parsing and data processing methods
- Added support for Home Assistant's `/api/history/period/` endpoint
- Implemented statistical calculations and data filtering algorithms
- Enhanced error handling with graceful fallback mechanisms

## [1.2.0] - Previous Release
- Entity registry access via WebSocket API
- MQTT publish/subscribe functionality  
- Enhanced entity and device management tools
- Pagination support for large Home Assistant installations

## [1.1.0] - Previous Release
- Home Assistant CLI command execution
- Entity and device listing capabilities
- Enhanced security and configuration options

## [1.0.0] - Initial Release
- Basic file operations (read, write, delete, list)
- Directory management
- File search functionality
- API key authentication
- Configurable allowed directories and read-only mode
