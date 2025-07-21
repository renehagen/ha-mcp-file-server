# MCP File Server for Home Assistant

A simple Model Context Protocol (MCP) server addon for Home Assistant that allows remote file management through MCP clients.

## Features

- **File Operations**: List, read, write, create, and delete files and directories
- **Search**: Search for text patterns within files
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

## Usage

### Connecting from MCP Clients

Once installed and started, the MCP server is available at:
```
http://homeassistant.local:6789/api/mcp
```

### Example Client Configuration

**For Claude Code:**
```bash
# Without API key
claude mcp add ha-files http://homeassistant.local:6789/api/mcp

# With API key
claude mcp add ha-files "http://homeassistant.local:6789/api/mcp?code=YOUR_API_KEY"
```

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

## 🚀 AI-Powered Use Cases

This MCP server unlocks powerful AI-driven Home Assistant management capabilities. Here are the top 5 use cases:

### 1. 🔍 **Smart Entity Management & Dependency Tracking**
AI can analyze your entire Home Assistant configuration to provide intelligent entity management:

**Example scenarios:**
- *"Find all places where `sensor.living_room_temperature` is referenced"* - AI searches all YAML files, automations, dashboards, and scripts
- *"I want to rename `light.bedroom` to `light.master_bedroom` - show me what will break"* - AI identifies dependencies before you make changes
- *"Clean up my configuration - find orphaned entities that are defined but never used"* - AI detects unused sensors, switches, and automations
- *"Map dependencies for my lighting system"* - AI creates a visual dependency graph showing which automations control which lights

### 2. 🩺 **Automated Troubleshooting & Diagnostics**
When things break, AI becomes your personal Home Assistant expert:

**Example scenarios:**
- *"My bedroom lights automation stopped working yesterday"* - AI searches logs, checks recent config changes, identifies the automation file, and pinpoints the exact issue
- *"Why is my Z-Wave network unstable?"* - AI analyzes Z-Wave logs, device configurations, and network topology to identify interference or failing devices
- *"Zigbee devices keep going unavailable"* - AI correlates device logs with network events and suggests specific fixes
- *"My climate control is acting weird"* - AI traces climate entity through all automations, templates, and scripts to find the root cause

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