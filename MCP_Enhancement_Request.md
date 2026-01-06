# MCP Server Enhancement Request - ✅ IMPLEMENTED

## Feature Request: Historical Entity Data Retrieval

### Implementation Status: ✅ COMPLETED (January 6, 2024)

The `get_ha_entity_history` function has been successfully implemented with all requested features and enhancements.

### Implementation Summary

**✅ Core Function Implemented:**
- Function name: `get_ha_entity_history`  
- All required parameters supported
- Flexible time format support (relative and ISO 8601)
- Statistical analysis for numeric sensors
- Smart filtering with minimal_change parameter

**✅ Key Features Delivered:**
- **Time Format Support**: Both relative formats (`-6h`, `-24h`, `-7d`) and ISO 8601 timestamps
- **Data Processing**: Automatic calculation of statistics (min, max, average, changes per hour)
- **Smart Filtering**: Optional `minimal_change` parameter to filter out sensor noise
- **Error Handling**: Robust error handling with graceful degradation
- **Performance Optimized**: Uses Home Assistant's efficient history API

**✅ Files Added/Modified:**
- `src/mcp_server.py`: Added tool definition and execution logic
- `src/supervisor_api.py`: Implemented core functionality with comprehensive time parsing and statistical analysis
- `examples/test_entity_history.py`: Test script for validation
- `examples/ENTITY_HISTORY_EXAMPLES.md`: Comprehensive usage examples
- `README.md`: Updated with detailed documentation
- `CHANGELOG.md`: Release notes and version history

**✅ Response Format Implemented:**
```json
{
    "entity_id": "sensor.temperature",
    "query_period": {
        "start": "2024-01-06T04:00:00Z",
        "end": "2024-01-06T10:00:00Z", 
        "duration_hours": 6.0
    },
    "total_changes": 45,
    "state_changes": [...],
    "statistics": {
        "type": "numeric",
        "changes_per_hour": 7.5,
        "value_statistics": {
            "min": 20.8, "max": 22.1, "average": 21.4
        }
    }
}
```

### Usage Examples Now Available

The implementation includes comprehensive examples for:
- **HVAC System Analysis**: Temperature modulation patterns and heating cycles
- **Automation Debugging**: State change tracking and timing analysis  
- **Performance Monitoring**: System efficiency and switching frequency analysis
- **Energy Optimization**: Usage patterns and inefficiency identification
- **Predictive Maintenance**: Unusual pattern detection

### Problem Statement

The current MCP Home Assistant server only provides real-time entity states through `list_ha_entities_devices`. For comprehensive analysis of heating systems, HVAC performance, and automation debugging, historical state changes are crucial. Without this capability, it's impossible to:

- Analyze temperature modulation patterns over time
- Identify system inefficiencies and optimization opportunities  
- Debug automation timing issues
- Perform data-driven heating system improvements

### Proposed Solution

Add a new MCP tool function `get_ha_entity_history` that retrieves historical state changes for Home Assistant entities.

### Function Specification

**Function Name:** `get_ha_entity_history`

**Parameters:**
- `entity_id` (string, required): Target entity ID (e.g., 'sensor.diyless_thermostat_1_ch_temperature')
- `start_time` (string, optional): Start time in ISO 8601 format or relative format ('-6h', '-24h', '-7d'). Default: 12 hours ago
- `end_time` (string, optional): End time in ISO 8601 format or 'now'. Default: current time
- `limit` (integer, optional): Maximum number of state changes to return. Default: 1000
- `minimal_change` (float, optional): For numeric sensors, filter out changes smaller than this value

**Returns:** Dictionary containing historical state changes with timestamps, previous states, statistics, and metadata.

### Response Format Structure

The function should return a structured response containing:
- Entity ID and query period information
- Total number of changes found
- Array of state changes with timestamps and values
- Statistical summary for numeric sensors (min, max, average, changes per hour)
- Query execution metadata

### Use Cases

#### HVAC System Analysis
Analyze CV temperature modulation patterns over specific time periods to identify heating cycles and system efficiency.

#### Automation Debugging  
Track state changes of flame sensors, pumps, and thermostats to debug timing issues in heating automations.

#### Performance Monitoring
Monitor switching frequencies and system responsiveness over extended periods to identify potential issues.

### Implementation Requirements

**Primary Method:** Home Assistant REST API using the `/api/history/period/` endpoint
**Fallback Method:** Direct SQLite database access when API is unavailable
**Time Format Support:** Both ISO 8601 absolute timestamps and relative formats ('-6h', '-24h', '-7d')
**Data Processing:** Calculate statistics, filter noise, and format data for analysis

### Error Handling Requirements

- Validate entity IDs and provide helpful error messages
- Handle API timeouts and connection issues with retry logic  
- Manage large datasets through pagination and chunking
- Graceful degradation when Home Assistant is unavailable

### Benefits

1. **Comprehensive Analysis**: Enable deep analysis of heating system performance
2. **Data-Driven Optimization**: Make informed decisions based on historical patterns  
3. **Debugging Capability**: Quickly identify when and why automations fail
4. **Performance Monitoring**: Track system efficiency over time
5. **Predictive Maintenance**: Identify patterns that predict failures

### Priority and Timeline

**Priority Level:** High - Essential for effective home automation analysis and optimization

**Estimated Development Time:** 4-6 hours total
- API integration and data retrieval: 2 hours
- Data processing and statistics calculation: 2 hours
- Error handling, validation, and testing: 2 hours

### Configuration Requirements

Support for configurable defaults including:
- Default lookback period (hours)
- Maximum records per request
- Enable/disable statistics calculation
- Database fallback options
- Rate limiting settings

This enhancement would significantly improve the MCP server's analytical capabilities and enable data-driven home automation optimization.