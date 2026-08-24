#!/usr/bin/with-contenv bashio

CONFIG_PATH=/data/options.json

PORT=$(bashio::config 'port')
API_KEY=$(bashio::config 'api_key')
READ_ONLY=$(bashio::config 'read_only')
MAX_FILE_SIZE_MB=$(bashio::config 'max_file_size_mb')
ENABLE_HA_CLI=$(bashio::config 'enable_ha_cli')
ENABLE_BACKUP_INSPECTION=$(bashio::config 'enable_backup_inspection')
BACKUP_ALLOW_CONTENT=$(bashio::config 'backup_allow_content')
BACKUP_MAX_DOWNLOAD_MB=$(bashio::config 'backup_max_download_mb')
ALLOWED_SERVICES=$(bashio::config 'allowed_services' || echo "")
if [ "$ALLOWED_SERVICES" = "null" ]; then
  ALLOWED_SERVICES=""
fi

# Get allowed directories (bashio returns them as newline-separated values)
ALLOWED_DIRS=$(bashio::config 'allowed_dirs')

# Export environment variables
export MCP_PORT=$PORT
export MCP_API_KEY=$API_KEY
export MCP_READ_ONLY=$READ_ONLY
export MCP_MAX_FILE_SIZE_MB=$MAX_FILE_SIZE_MB
export MCP_ENABLE_HA_CLI=$ENABLE_HA_CLI
export MCP_ENABLE_BACKUP_INSPECTION=$ENABLE_BACKUP_INSPECTION
export MCP_BACKUP_ALLOW_CONTENT=$BACKUP_ALLOW_CONTENT
export MCP_BACKUP_MAX_DOWNLOAD_MB=$BACKUP_MAX_DOWNLOAD_MB
export MCP_ALLOWED_DIRS="$ALLOWED_DIRS"
export MCP_ALLOWED_SERVICES="$ALLOWED_SERVICES"

bashio::log.info "Starting MCP File Server on port $PORT"
bashio::log.info "Read-only mode: $READ_ONLY"
bashio::log.info "HA CLI enabled: $ENABLE_HA_CLI"
bashio::log.info "Backup inspection enabled: $ENABLE_BACKUP_INSPECTION"
bashio::log.info "Backup content return enabled: $BACKUP_ALLOW_CONTENT"
bashio::log.info "Allowed directories: $ALLOWED_DIRS"
bashio::log.info "Allowed Home Assistant services: $ALLOWED_SERVICES"

# Start the MCP server
cd /app
exec /opt/venv/bin/python mcp_server.py
