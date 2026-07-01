# MCP File Server for Home Assistant

A simple Model Context Protocol (MCP) server addon for Home Assistant that allows remote file management through MCP clients.

## Features

- **File Operations**: List, read, write, create, and delete files and directories
- **Search**: Search for text patterns within files
- **HA CLI Commands**: Execute Home Assistant CLI commands safely (optional)
- **HA Service Calls**: Call allowlisted Home Assistant services, including reloads and setpoints (optional)
- **Entity Management**: List and filter Home Assistant entities, devices, and services
- **Historical Analysis**: Retrieve and analyze historical entity state changes for HVAC optimization and debugging
- **Log Diagnostics**: Query Home Assistant logs by time, level, logger, and message text
- **MCP Add-on Management**: Inspect MCP runtime flags, add-on config, logs, stats, and restart the add-on
- **Automation Debugging**: Validate YAML, run config checks, and read automation traces
- **Security**: API key authentication and path validation
- **Configurable**: Set allowed directories, read-only mode, and file size limits
- **Remote Access**: HTTP/SSE transport for remote MCP clients
- **MQTT Integration**: Publish and subscribe to MQTT topics

## Installation

1. Copy this addon folder to your Home Assistant `/addons` directory
2. In Home Assistant, go to **Settings** → **Add-ons** → **Add-on Store**
3. Click the three dots menu → **Check for updates**
4. Find "MCP File Server" in the Local add-ons section
5. Click on it and then click **Install**

## Configuration

Configure the addon through the Home Assistant UI:

- **port**: Port for the MCP server (default: 6789)
- **api_key**: Optional API key for authentication
- **allowed_dirs**: List of directories the server can access (default: ["/config", "/share"])
- **read_only**: Enable read-only mode (default: false)
- **max_file_size_mb**: Maximum file size in MB (default: 10)
- **enable_ha_cli**: Enable HA CLI command execution (default: false)
- **allowed_services**: Home Assistant services that AI clients may call when `enable_ha_cli` is true and `read_only` is false

## Usage

### Connecting from MCP Clients

Once installed and started, the MCP server is available at:
```
http://homeassistant.local:6789/api/mcp
```

### Example Client Configuration

**For Claude Code CLI:**
```bash
# Without API key (use IP address if homeassistant.local doesn't resolve)
claude mcp add ha-files http://homeassistant.local:6789/api/mcp --transport http
# or
claude mcp add ha-files http://192.168.1.93:6789/api/mcp --transport http

# With API key
claude mcp add ha-files "http://homeassistant.local:6789/api/mcp?code=YOUR_API_KEY" --transport http
```

**Note:** The `--transport http` flag is required for Claude Code CLI to properly recognize this as an HTTP-based MCP server.

**For Claude Desktop or other MCP clients:**
```json
{
  "mcpServers": {
    "ha-files": {
      "transport": {
        "type": "http", 
        "url": "http://homeassistant.local:6789/api/mcp"
      }
    }
  }
}
```

### Available Tools

- `list_directory`: List files and directories in a path
- `read_file`: Read contents of a file
- `write_file`: Write content to a file
- `create_directory`: Create a new directory
- `delete_path`: Delete a file or directory
- `search_files`: Search for files containing specific text
- `read_file_filtered`: Read file with filtering support for large files
- `query_logs`: Query Home Assistant log files from the tail with time, level, logger, and text filters
- `get_mcp_runtime_status`: Show effective runtime flags, including whether `MCP_ENABLE_HA_CLI` is active
- `validate_yaml_file`: Validate YAML syntax, duplicate keys, and ambiguous values like `off`
- `validate_automation_file`: Validate automation YAML structure and optionally run `check_config`
- `execute_ha_cli`: Execute Home Assistant CLI commands (when enabled)
- `list_ha_entities_devices`: List all Home Assistant entities, devices, and services via REST API (when enabled)
- `get_ha_entity_registry`: Get all entities from the entity registry with platform and unique_id information (when enabled)
- `get_ha_entity_history`: Get historical state changes, including relative minute windows and unavailable transitions (when enabled)
- `get_ha_entities_history`: Get multi-entity history summaries with min/max/average, unavailable periods, and timelines (when enabled)
- `get_states`: Get compact current-state snapshots for multiple entities in one API call (when enabled)
- `get_mcp_addon_info`: Inspect the MCP add-on state, options/config, stats, runtime flags, and optional logs (when enabled)
- `get_mcp_addon_logs`: Read recent logs for the MCP add-on (when enabled)
- `restart_mcp_addon`: Restart the MCP add-on through Supervisor (when enabled and not read-only)
- `call_service`: Call an allowlisted Home Assistant service through the WebSocket API (when enabled)
- `reload_automations`, `reload_scripts`, `reload_template_entities`, `reload_python_scripts`: Reload HA configuration areas without a restart (when enabled)
- `reload_integration`: Reload one Home Assistant config entry by `entry_id` (when enabled)
- `check_config`: Run Home Assistant's core config check (when enabled)
- `get_automation_trace`: Fetch and summarize recent automation traces (when enabled)

### Home Assistant Service Calls, Reloads, and Traces

When `enable_ha_cli` is `true`, the server can also use Home Assistant's REST and WebSocket APIs for controlled live operations. Write/reload tools are blocked when `read_only` is `true` and must match `allowed_services`.

Default `allowed_services`:

```yaml
allowed_services:
  - automation.reload
  - automation.turn_on
  - automation.turn_off
  - script.reload
  - template.reload
  - python_script.reload
  - homeassistant.check_config
  - homeassistant.reload_config_entry
  - homeassistant.update_entity
  - number.set_value
  - select.select_option
```

Examples:

```text
call_service(domain="number", service="set_value", target={"entity_id": "number.example"}, data={"value": 0})
call_service(domain="homeassistant", service="check_config")
reload_automations()
reload_integration(entry_id="01J...")
check_config()
get_automation_trace(entity_id="automation.zendure_safety_stop", last_n=3)
```

Validation tools are read-only file/API operations. `validate_yaml_file` and `validate_automation_file` work against configured `allowed_dirs`; `validate_automation_file(run_check_config=true)` additionally calls Home Assistant's config check.

### Diagnostics: Logs, States, and History

`query_logs` reads the tail of a log file inside `allowed_dirs` and does not require `enable_ha_cli`. It is useful for quickly narrowing Home Assistant errors without returning the whole log file.

```text
query_logs(level=["ERROR", "WARNING"], since="-30m", limit=25)
query_logs(logger_filter="custom_components.zendure", text_filter=["battery", "unavailable"], match_mode="all")
query_logs(path="/config/home-assistant.log", text_filter="Traceback", max_bytes=1048576)
```

When `enable_ha_cli` is `true`, `get_states` returns a compact live snapshot for multiple entities in one REST call:

```text
get_states(
  entity_ids=["sensor.battery_power", "number.zendure_manager_manual_power"],
  attributes=["friendly_name", "unit_of_measurement"]
)
```

`get_ha_entity_history` now accepts minute-based relative windows such as `-30m` and `-90m`, and can focus on unavailable edges:

```text
get_ha_entity_history(entity_id="sensor.battery_power", start_time="-90m", limit=200)
get_ha_entity_history(entity_id="sensor.battery_power", start_time="-24h", unavailable_transitions_only=true)
get_ha_entities_history(
  entity_ids=["sensor.sma_power", "sensor.zendure_power", "sensor.zendure_state"],
  start_time="-90m",
  include_timeline=true,
  include_state_changes=false
)
```

More focused examples are in `/examples/BATCH2_DIAGNOSTICS_EXAMPLES.md`.

### MCP Add-on Management

`get_mcp_runtime_status` is always available and reports the effective runtime flags of the running container, including `ha_cli_enabled`, `read_only`, and `allowed_services`.

When `enable_ha_cli` is `true`, add-on management tools use the Supervisor API:

```text
get_mcp_addon_info(include_logs=true, log_lines=100)
get_mcp_addon_logs(lines=200)
restart_mcp_addon()
```

`restart_mcp_addon` is blocked when `read_only` is `true`. It restarts the add-on itself, so the MCP request may disconnect while Supervisor restarts the container.

### Home Assistant CLI Commands

When `enable_ha_cli` is set to `true`, the server provides a secure way to execute Home Assistant CLI commands. This feature includes:

**Safety Features:**
- Only specific HA CLI commands are allowed (ha addons, ha supervisor, ha core, etc.)
- Dangerous patterns are blocked (file operations, system commands, shell injection)
- Commands have a timeout limit (default 30 seconds)
- Output is limited to 1MB to prevent resource exhaustion

**Allowed Commands:**
- `ha addons` - Manage add-ons (logs, info, stats, etc.)
- `ha supervisor` - Supervisor information and operations
- `ha core` - Home Assistant core operations
- `ha host` - Host system information
- `ha network` - Network configuration
- `ha os` - Operating system operations
- `ha audio` - Audio system management
- `ha multicast` - Multicast DNS operations
- `ha dns` - DNS configuration
- `ha jobs` - View running jobs
- `ha resolution` - View system resolution issues
- `ha info` - General system information
- `ha --help` - Help information

**Example Usage:**
```
execute_ha_cli("ha addons logs core_matter_server")
execute_ha_cli("ha supervisor info")
execute_ha_cli("ha core logs")
```

### Home Assistant Entity & Device Management

When `enable_ha_cli` is set to `true`, the server also provides direct access to Home Assistant's REST API for comprehensive entity and device management:

**`list_ha_entities_devices` Tool:**
This tool provides complete visibility into your Home Assistant setup by retrieving:

- **All Entities**: Every sensor, light, switch, climate device, etc. with their current states
- **All Devices**: Physical and logical devices registered in Home Assistant
- **All Services**: Available services you can call (like `light.turn_on`, `climate.set_temperature`)
- **Summary Statistics**: Quick overview with counts and totals

**Parameters (all optional):**
- `limit` (integer, default: 50): Maximum number of items to return per request
- `offset` (integer, default: 0): Number of items to skip for pagination
- `domain_filter` (string): Filter entities by domain (e.g., 'light', 'sensor', 'switch', 'climate')
- `entity_filter` (string): Search pattern to filter entity IDs (case-insensitive)
- `include_entities` (boolean, default: true): Include entities in response
- `include_devices` (boolean, default: true): Include devices in response
- `include_services` (boolean, default: false): Include services in response

**Example Usage:**
```
# Get first 10 devices
list_ha_entities_devices(limit=10, include_entities=false)

# Get all lights
list_ha_entities_devices(domain_filter="light", limit=100)

# Search for bedroom entities
list_ha_entities_devices(entity_filter="bedroom", limit=20)

# Get next page of results
list_ha_entities_devices(limit=50, offset=50)

# Get only summary (no full data)
list_ha_entities_devices(limit=0, include_entities=true, include_devices=true)
```

**Example Response:**
```json
{
  "entities": {
    "items": [
      {
        "entity_id": "light.living_room",
        "state": "on",
        "attributes": {"brightness": 255, "color_temp": 370},
        "last_changed": "2025-11-09T10:30:00"
      }
    ],
    "total_count": 150,
    "returned_count": 10,
    "offset": 0,
    "limit": 10
  },
  "devices": {
    "items": [
      {
        "id": "abc123",
        "name": "Living Room Light",
        "manufacturer": "Philips",
        "model": "Hue Bulb"
      }
    ],
    "total_count": 45,
    "returned_count": 10,
    "offset": 0,
    "limit": 10
  },
  "summary": {
    "entity_count": 150,
    "device_count": 45
  }
}
```

**Key Benefits:**
- **Pagination Support**: Handle large systems with thousands of entities efficiently
- **Domain Filtering**: Focus on specific entity types (lights, sensors, etc.)
- **Search Capability**: Find entities by name pattern
- **Real-time Data**: Get current states and attributes for all entities
- **Device Information**: Access device registry data including manufacturers, models, and relationships
- **Service Discovery**: Understand what actions are available in your system

**Security Note:** HA CLI access (including entity/device listing) is disabled by default. Only enable it if you need programmatic access to your Home Assistant system and understand the security implications.

### Entity Registry Access

When `enable_ha_cli` is set to `true`, the server provides efficient access to the Home Assistant entity registry through the `get_ha_entity_registry` tool.

**`get_ha_entity_registry` Tool:**
This is the **most efficient way** to retrieve all entities from Home Assistant. It provides complete registry information including:

- **Platform Information**: Know which integration created each entity (mqtt, zwave, zigbee, esphome, etc.)
- **Unique IDs**: Access the unique_id field that can be matched with device topics (especially useful for MQTT)
- **Original Names**: Get the original entity names before customization
- **Registry Metadata**: Access all entity registry data in a single API call

**Key Advantages Over `list_ha_entities_devices`:**
- ✅ **Single API Call**: Retrieves all 700+ entities at once via WebSocket API
- ✅ **Platform Filtering**: Built-in filtering by platform (mqtt, zwave, etc.)
- ✅ **Unique ID Access**: Essential for matching entities to device topics
- ✅ **Registry-Only Data**: Includes information not available in entity states
- ✅ **Pagination Support**: Control response size with limit and offset parameters

### Historical Entity Data Analysis

The `get_ha_entity_history` tool provides comprehensive historical state analysis for Home Assistant entities. This is essential for:

- **HVAC System Analysis**: Monitor heating/cooling patterns and efficiency
- **Automation Debugging**: Track state changes to identify timing issues
- **Performance Monitoring**: Analyze system behavior over time
- **Energy Optimization**: Understand usage patterns and inefficiencies
- **Predictive Maintenance**: Identify unusual patterns that might indicate problems

**`get_ha_entity_history` Tool:**

**Parameters:**
- `entity_id` (required): Target entity ID (e.g., 'sensor.diyless_thermostat_1_ch_temperature')
- `start_time` (optional): Start time in ISO 8601 format or relative format ('-30m', '-90m', '-6h', '-24h', '-7d'). Default: 12 hours ago
- `end_time` (optional): End time in ISO 8601 format or 'now'. Default: current time
- `limit` (optional): Maximum number of state changes to return. Default: 1000
- `minimal_change` (optional): For numeric sensors, filter out changes smaller than this value
- `unavailable_transitions_only` (optional): Only return transitions to or from `unavailable`

**Time Format Support:**
```bash
# Relative formats (recommended)
"-30m"   # 30 minutes ago
"-90m"   # 90 minutes ago
"-6h"    # 6 hours ago
"-24h"   # 24 hours ago
"-7d"    # 7 days ago
"-2w"    # 2 weeks ago

# ISO 8601 formats
"2024-01-06T10:00:00Z"         # UTC time
"2024-01-06T10:00:00+01:00"    # With timezone
"now"                          # Current time
```

**Example Usage:**

```bash
# Analyze thermostat temperature over last 6 hours
get_ha_entity_history(
    entity_id="sensor.diyless_thermostat_1_ch_temperature",
    start_time="-6h",
    minimal_change=0.1  # Filter out noise < 0.1°C
)

# Monitor heating system efficiency (24 hours)
get_ha_entity_history(
    entity_id="binary_sensor.flame_sensor",
    start_time="-24h",
    limit=500
)

# Debug automation timing issues
get_ha_entity_history(
    entity_id="switch.heating_pump",
    start_time="-12h",
    end_time="now"
)
```

**Response Format:**
```json
{
    "entity_id": "sensor.temperature",
    "query_period": {
        "start": "2024-01-06T04:00:00Z",
        "end": "2024-01-06T10:00:00Z", 
        "duration_hours": 6.0
    },
    "total_changes": 45,
    "state_changes": [
        {
            "timestamp": "2024-01-06T04:15:23Z",
            "state": "21.5",
            "numeric_value": 21.5,
            "unit": "°C",
            "friendly_name": "Living Room Temperature"
        }
    ],
    "statistics": {
        "type": "numeric",
        "total_changes": 45,
        "changes_per_hour": 7.5,
        "value_statistics": {
            "min": 20.8,
            "max": 22.1, 
            "average": 21.4,
            "total_variation": 1.3
        },
        "unit": "°C"
    }
}
```

**Key Features:**
- **Flexible Time Ranges**: Support for both relative and absolute time specifications
- **Smart Filtering**: Optional minimal_change parameter to reduce noise in sensor data
- **Statistical Analysis**: Automatic calculation of min, max, average, and change frequency
- **Multiple Data Types**: Works with numeric sensors, binary sensors, and text-based entities
- **Error Handling**: Graceful handling of non-existent entities and API failures
- **Performance Optimized**: Uses Home Assistant's efficient history API with pagination

**Use Cases:**
1. **Heating System Analysis**: Track temperature modulation patterns and heating cycles
2. **Energy Optimization**: Analyze usage patterns to identify inefficiencies  
3. **Automation Debugging**: Monitor state changes to identify timing issues
4. **System Monitoring**: Track switching frequencies for predictive maintenance
5. **Performance Analysis**: Compare system behavior across different time periods

For detailed examples and advanced use cases, see `/examples/ENTITY_HISTORY_EXAMPLES.md`.

## File Operations

**Parameters (all optional):**
- `limit` (integer, default: 100): Maximum number of entities to return (set to 0 for count only)
- `offset` (integer, default: 0): Number of entities to skip for pagination
- `platform_filter` (string): Filter entities by platform (e.g., 'mqtt', 'zwave', 'zigbee', 'esphome')
- `entity_filter` (string): Search pattern to filter entity IDs (case-insensitive)
- `fields` (array): List of field names to return. If not specified, returns all fields. **Use this to dramatically reduce token usage!**
  - Common fields: `entity_id`, `unique_id`, `platform`, `original_name`, `device_id`, `area_id`, `disabled_by`
  - **Token savings**: Using `["entity_id", "unique_id"]` reduces tokens by ~95% (from ~19k to ~1k per 30 entities)

**Example Usage:**
```
# Get first 100 MQTT entities (default limit)
get_ha_entity_registry(platform_filter="mqtt")

# Get next 100 MQTT entities
get_ha_entity_registry(platform_filter="mqtt", offset=100)

# Get all motion sensor entities, 50 at a time
get_ha_entity_registry(entity_filter="motion", limit=50)

# Get count of all entities without returning data
get_ha_entity_registry(limit=0)

# COMPACT MODE: Get only entity_id and unique_id (95% token reduction!)
get_ha_entity_registry(
    platform_filter="mqtt",
    limit=100,
    fields=["entity_id", "unique_id"]
)

# Get essential fields for MQTT analysis
get_ha_entity_registry(
    platform_filter="mqtt",
    limit=100,
    fields=["entity_id", "unique_id", "platform", "original_name"]
)

# Get all Zigbee entities containing "bedroom", first 25, compact
get_ha_entity_registry(
    platform_filter="zigbee",
    entity_filter="bedroom",
    limit=25,
    fields=["entity_id", "unique_id", "platform"]
)
```

**Example Response:**
```json
{
  "entities": [
    {
      "entity_id": "sensor.beweging_gang_beweging",
      "platform": "mqtt",
      "unique_id": "homey-5d7a3bdaf7af713c2c45cea6_beweging-gang_alarm-motion",
      "original_name": "Beweging Gang - Beweging",
      "device_id": "abc123",
      "config_entry_id": "xyz789",
      "disabled_by": null,
      "hidden_by": null
    }
  ],
  "pagination": {
    "returned_count": 1,
    "filtered_count": 150,
    "total_count": 727,
    "offset": 0,
    "limit": 100
  },
  "timestamp": "now",
  "filters_applied": {
    "platform": "mqtt",
    "entity_pattern": "beweging",
    "fields": "all"
  }
}
```

**Compact Response Example (with fields parameter):**
```json
{
  "entities": [
    {
      "entity_id": "sensor.beweging_gang_beweging",
      "unique_id": "homey-5d7a3bdaf7af713c2c45cea6_beweging-gang_alarm-motion"
    },
    {
      "entity_id": "sensor.beweging_keuken_beweging",
      "unique_id": "homey-5d7a3bdaf7af713c2c45cea6_beweging-keuken_alarm-motion"
    }
  ],
  "pagination": {
    "returned_count": 2,
    "filtered_count": 725,
    "total_count": 727,
    "offset": 0,
    "limit": 100
  },
  "filters_applied": {
    "platform": "mqtt",
    "fields": ["entity_id", "unique_id"]
  }
}
```

**Token Usage Comparison:**
- **Full response** (all fields): ~19,000 tokens per 30 entities
- **Compact response** (2 fields): ~1,000 tokens per 100 entities (95% reduction!)
- To get all 725 MQTT entities:
  - Full: 25 batches × 19k = 475k tokens ❌ (exceeds limits)
  - Compact: 8 batches × 1k = 8k tokens ✅ (well within limits)

**Use Cases:**
- 🔍 **MQTT Entity Discovery**: Find all MQTT entities and their unique_ids for topic matching
- 🏠 **Platform Auditing**: Identify which entities belong to which integrations
- 🔧 **Entity Management**: Clean up entities by platform or naming patterns
- 📊 **System Analysis**: Get complete overview of all registered entities in one call
- 🔄 **Migration Planning**: Identify entities before migrating between platforms

**Security Note:** HA CLI access (including entity/device listing) is disabled by default. Only enable it if you need programmatic access to your Home Assistant system and understand the security implications.

## 🚀 AI-Powered Use Cases

This MCP server unlocks powerful AI-driven Home Assistant management capabilities. Here are the top 5 use cases:

### 1. 🔍 **Smart Entity Management & Dependency Tracking**
AI can analyze your entire Home Assistant configuration AND live system state to provide intelligent entity management:

**Example scenarios:**
- *"Find all places where `sensor.living_room_temperature` is referenced"* - AI searches all YAML files, automations, dashboards, and scripts
- *"I want to rename `light.bedroom` to `light.master_bedroom` - show me what will break"* - AI identifies dependencies before you make changes
- *"Clean up my configuration - find orphaned entities that are defined but never used"* - AI compares live entities with configuration files to detect unused sensors, switches, and automations
- *"Show me all my Philips Hue devices and their current states"* - AI uses the entity/device listing to provide real-time device inventory
- *"Map dependencies for my lighting system"* - AI creates a visual dependency graph showing which automations control which lights, including current states

### 2. 🩺 **Automated Troubleshooting & Diagnostics**
When things break, AI becomes your personal Home Assistant expert with access to both configuration and live system state:

**Example scenarios:**
- *"My bedroom lights automation stopped working yesterday"* - AI searches logs, checks recent config changes, examines current entity states, and pinpoints the exact issue
- *"Why is my Z-Wave network unstable?"* - AI analyzes Z-Wave logs, device configurations, current device states, and network topology to identify interference or failing devices
- *"Zigbee devices keep going unavailable"* - AI correlates device logs with live device registry data and suggests specific fixes
- *"My climate control is acting weird"* - AI traces climate entity through all automations, templates, and scripts while checking current sensor readings and device states
- *"Which of my 150 entities are currently unavailable?"* - AI instantly scans all live entity states to identify offline devices

### 3. 🔒 **Configuration Auditing & Security Analysis**
AI performs comprehensive security and best practices review:

**Example scenarios:**
- *"Audit my Home Assistant security"* - AI scans for exposed entities, weak authentication, unsafe automations, and external access risks
- *"Check my configuration for deprecated syntax"* - AI identifies outdated YAML patterns, deprecated integrations, and suggests modern alternatives
- *"Optimize my configuration for performance"* - AI finds resource-heavy automations, inefficient sensors, and suggests optimizations
- *"Validate my backup strategy"* - AI ensures all critical configurations are properly backed up and restorable

### 4. 🤖 **Intelligent Automation Generation**
AI learns from your existing setup to create new automations that match your style:

**Example scenarios:**
- *"Create a morning routine automation like my existing evening routine"* - AI analyzes patterns and generates similar automations
- *"Build a dashboard for my new smart thermostat"* - AI studies your existing dashboards and creates matching layouts
- *"Generate motion-activated lighting for my hallway based on how I've set up other rooms"* - AI replicates successful patterns
- *"Create a plant watering automation using my soil moisture sensors"* - AI generates complex logic based on your sensor setup and automation patterns

### 5. 🔧 **Proactive System Maintenance & Optimization**
AI continuously monitors and maintains your Home Assistant health:

**Example scenarios:**
- *"Perform a monthly system health check"* - AI analyzes performance metrics, identifies growing log files, checks integration status, and suggests maintenance tasks
- *"Prepare for Home Assistant 2024.12 update"* - AI reviews breaking changes documentation against your configuration and predicts what needs updating
- *"My system feels slow - what's causing it?"* - AI analyzes automation frequency, database size, resource usage, and identifies performance bottlenecks
- *"Detect configuration drift"* - AI compares current setup against your documented standards and identifies manual changes that may cause issues

### 🎯 **Why This Is Game-Changing**

Unlike generic AI assistants that give general advice, this MCP server gives AI **direct access** to your actual configuration files. This means:

- **Contextual Solutions**: AI sees your exact setup and provides specific fixes
- **Safe Changes**: AI understands dependencies before suggesting modifications  
- **Learning Capability**: AI learns your patterns and preferences from your existing configurations
- **Proactive Maintenance**: AI can regularly audit your system without manual intervention
- **Expert-Level Knowledge**: AI applies Home Assistant best practices to your specific setup

This transforms AI from a general helper into a **personalized Home Assistant expert** that knows your system inside and out.

## ⚠️ IMPORTANT SECURITY WARNING

**AI systems can make mistakes and potentially cause harm to your Home Assistant configuration.** Before using this MCP server:

- **ALWAYS have a complete backup** of your Home Assistant configuration before allowing AI write access
- **Start with read-only mode** (`read_only: true`) to test functionality safely
- **Test with non-critical systems first** before giving AI access to important automations
- **Review AI-suggested changes** carefully before applying them to production systems
- **Monitor AI actions** and be prepared to restore from backup if needed

AI can be incredibly helpful, but it's not infallible. Your backup is your safety net.

## Security

- Always use an API key in production
- The server validates all paths to prevent directory traversal
- Only directories listed in `allowed_dirs` can be accessed
- Consider using read-only mode if write access is not needed

## Development

### Local Testing

To test the server locally:

```bash
cd src
pip install -r requirements.txt
export MCP_PORT=6789
export MCP_API_KEY="test-key"
export MCP_ALLOWED_DIRS='["/tmp/test"]'
export MCP_ENABLE_HA_CLI=false  # Set to true to enable HA CLI commands
python mcp_server.py
```

### Building the Addon

The addon is automatically built when installed through Home Assistant.

## Troubleshooting

- Check the addon logs in Home Assistant for error messages
- Ensure the configured port is not already in use
- Verify the allowed directories exist and are accessible
- Test connectivity with: `curl http://homeassistant.local:6789/health`

## License

MIT
