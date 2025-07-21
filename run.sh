#!/usr/bin/with-contenv bashio

CONFIG_PATH=/data/options.json

PORT=$(bashio::config 'port')
API_KEY=$(bashio::config 'api_key')
READ_ONLY=$(bashio::config 'read_only')
MAX_FILE_SIZE_MB=$(bashio::config 'max_file_size_mb')

# Get allowed directories (bashio returns them as newline-separated values)
ALLOWED_DIRS=$(bashio::config 'allowed_dirs')

# Export environment variables
export MCP_PORT=$PORT
export MCP_API_KEY=$API_KEY
export MCP_READ_ONLY=$READ_ONLY
export MCP_MAX_FILE_SIZE_MB=$MAX_FILE_SIZE_MB
export MCP_ALLOWED_DIRS="$ALLOWED_DIRS"

bashio::log.info "Starting MCP File Server on port $PORT"
bashio::log.info "Read-only mode: $READ_ONLY"
bashio::log.info "Allowed directories: $ALLOWED_DIRS"

# Start the MCP server
cd /app
exec /opt/venv/bin/python mcp_server.py