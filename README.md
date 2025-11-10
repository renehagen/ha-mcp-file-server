# MCP File Server for Home Assistant

A simple Model Context Protocol (MCP) server addon for Home Assistant that allows remote file management through MCP clients.

## Features

- **File Operations**: List, read, write, create, and delete files and directories
- **Search**: Search for text patterns within files
- **HA CLI Commands**: Execute Home Assistant CLI commands safely (optional)
- **Security**: API key authentication and path validation
- **Configurable**: Set allowed directories, read-only mode, and file size limits
- **Remote Access**: HTTP/SSE transport for remote MCP clients

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
- `execute_ha_cli`: Execute Home Assistant CLI commands (when enabled)
- `list_ha_entities_devices`: List all Home Assistant entities, devices, and services via REST API (when enabled)

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