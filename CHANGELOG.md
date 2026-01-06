# CHANGELOG

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