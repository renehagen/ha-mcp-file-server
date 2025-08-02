# MCP Server Device Control Extension Plan

## Overview

This document outlines the plan to extend the Home Assistant MCP File Server to support device control and service calls, enabling full Home Assistant entity management through the MCP interface.

## Current State

### Working Features
- ✅ Supervisor API integration
- ✅ Add-on log access
- ✅ System information retrieval
- ✅ File management operations
- ✅ Authentication via SUPERVISOR_TOKEN

### Permissions Configured
```yaml
hassio_api: true
hassio_role: manager
homeassistant_api: true
auth_api: true
```

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   MCP Client    │────▶│   MCP Server     │────▶│  Supervisor API │
│  (Claude Code)  │     │  (Add-on)        │     │  http://supervisor
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                │
                                ▼
                        ┌──────────────────┐
                        │ Home Assistant   │
                        │ REST API         │
                        │ http://homeassistant:8123
                        └──────────────────┘
```

## Implementation Plan

### Phase 1: Home Assistant API Module

Create `src/homeassistant_api.py`:

```python
class HomeAssistantAPI:
    """Handle communication with Home Assistant REST API."""
    
    def __init__(self):
        self.base_url = "http://homeassistant:8123"
        self.token = os.getenv("HOMEASSISTANT_TOKEN") or os.getenv("SUPERVISOR_TOKEN")
    
    async def call_service(self, domain: str, service: str, entity_id: str, data: dict = None)
    async def get_state(self, entity_id: str)
    async def set_state(self, entity_id: str, state: str, attributes: dict = None)
    async def get_services(self)
    async def get_config(self)
```

### Phase 2: Extended CLI Commands

#### Service Control Commands
- `ha service call light.turn_on light.living_room`
- `ha service call switch.toggle switch.bedroom_fan`
- `ha service call climate.set_temperature climate.living_room '{"temperature": 22}'`
- `ha service call script.turn_on script.morning_routine`
- `ha service call automation.trigger automation.motion_lights`

#### State Management Commands
- `ha state get light.living_room`
- `ha state set input_boolean.vacation_mode on`
- `ha state list` (list all entities)
- `ha state history sensor.temperature` (get state history)

#### System Control Commands
- `ha core restart`
- `ha core stop`
- `ha core update`
- `ha core check_config`

#### Add-on Management Commands
- `ha addons start <addon_slug>`
- `ha addons stop <addon_slug>`
- `ha addons restart <addon_slug>`
- `ha addons update <addon_slug>`

### Phase 3: Authentication Enhancement

1. **Token Management**
   - Support for Long-Lived Access Tokens (LLAT)
   - Token validation and refresh
   - Secure token storage

2. **Configuration Options**
   ```yaml
   options:
     homeassistant_token: ""  # Optional LLAT
     allowed_domains: []      # Restrict service calls to specific domains
     allowed_entities: []     # Restrict control to specific entities
   ```

### Phase 4: Safety and Security Features

1. **Input Validation**
   - Entity ID format validation
   - Service name validation
   - Domain restrictions
   - Data type checking

2. **Rate Limiting**
   - Max requests per minute
   - Cooldown periods for critical operations
   - Concurrent request limits

3. **Audit Logging**
   - Log all state changes
   - Track service calls
   - User action history
   - Rollback information

4. **Permission Levels**
   - Read-only mode
   - Restricted domains
   - Entity whitelist/blacklist
   - Critical operation confirmation

### Phase 5: Enhanced MCP Tools

#### New Tool: `execute_service`
```json
{
  "name": "execute_service",
  "description": "Call a Home Assistant service",
  "inputSchema": {
    "type": "object",
    "properties": {
      "domain": {"type": "string"},
      "service": {"type": "string"},
      "entity_id": {"type": "string"},
      "data": {"type": "object"}
    },
    "required": ["domain", "service"]
  }
}
```

#### New Tool: `get_entity_state`
```json
{
  "name": "get_entity_state",
  "description": "Get the current state of an entity",
  "inputSchema": {
    "type": "object",
    "properties": {
      "entity_id": {"type": "string"}
    },
    "required": ["entity_id"]
  }
}
```

## Example Usage

### Turn on a Light
```bash
ha service call light.turn_on light.living_room
```

### Set Temperature
```bash
ha service call climate.set_temperature climate.living_room '{"temperature": 22, "hvac_mode": "heat"}'
```

### Toggle a Switch
```bash
ha service call switch.toggle switch.bedroom_fan
```

### Get Entity State
```bash
ha state get sensor.living_room_temperature
```

### Restart an Add-on
```bash
ha addons restart core_matter_server
```

## Benefits

1. **Unified Interface**: Single MCP interface for both file management and device control
2. **Secure Access**: Role-based permissions and token authentication
3. **Automation**: Enable Claude Code to automate Home Assistant tasks
4. **Debugging**: Easier troubleshooting with direct API access
5. **Flexibility**: Support for complex service calls and data

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Unauthorized device control | Entity/domain whitelisting |
| Accidental state changes | Confirmation for critical operations |
| API rate limiting | Request throttling and caching |
| Token exposure | Secure token storage and rotation |
| System instability | Rollback capabilities and audit logs |

## Testing Plan

1. **Unit Tests**
   - API communication
   - Command parsing
   - Error handling
   - Authentication

2. **Integration Tests**
   - Service calls
   - State management
   - Add-on control
   - Permission validation

3. **Security Tests**
   - Token validation
   - Permission enforcement
   - Input sanitization
   - Rate limiting

## Documentation Updates

1. Update README.md with new capabilities
2. Add examples for common use cases
3. Document security best practices
4. Create troubleshooting guide

## Timeline

- **Week 1**: Implement HomeAssistantAPI class
- **Week 2**: Add service call support
- **Week 3**: Implement state management
- **Week 4**: Add safety features and testing
- **Week 5**: Documentation and release

## Future Enhancements

1. **WebSocket Support**: Real-time state updates
2. **Batch Operations**: Multiple service calls in one command
3. **Scripting Support**: Execute YAML scripts
4. **Template Support**: Jinja2 template evaluation
5. **Event Monitoring**: Subscribe to Home Assistant events
6. **Backup Integration**: State snapshots before changes

## Conclusion

This extension will transform the MCP File Server into a comprehensive Home Assistant management tool, enabling powerful automation and control capabilities while maintaining security and reliability.