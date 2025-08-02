import os
import json
import logging
import subprocess
import asyncio
from typing import Dict, List, Any, Optional, Union
from fastapi import FastAPI, HTTPException, Request, Query
from pydantic import BaseModel
import uvicorn
from datetime import datetime

from file_handler import FileHandler
from supervisor_api import SupervisorAPI

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment
PORT = int(os.getenv("MCP_PORT", "6789"))
API_KEY = os.getenv("MCP_API_KEY", "")
READ_ONLY = os.getenv("MCP_READ_ONLY", "false").lower() == "true"
MAX_FILE_SIZE_MB = int(os.getenv("MCP_MAX_FILE_SIZE_MB", "10"))
ENABLE_HA_CLI = os.getenv("MCP_ENABLE_HA_CLI", "false").lower() == "true"

# Parse allowed directories - bashio provides them as newline-separated values
allowed_dirs_env = os.getenv("MCP_ALLOWED_DIRS", "")
if allowed_dirs_env.strip():
    try:
        ALLOWED_DIRS = json.loads(allowed_dirs_env)
    except json.JSONDecodeError:
        ALLOWED_DIRS = [d.strip() for d in allowed_dirs_env.strip().split('\n') if d.strip()]
else:
    ALLOWED_DIRS = []

# Initialize FastAPI app
app = FastAPI(title="MCP File Server", version="1.2.0")

# Initialize file handler
file_handler = FileHandler(
    allowed_dirs=ALLOWED_DIRS,
    read_only=READ_ONLY,
    max_file_size_mb=MAX_FILE_SIZE_MB
)

# JSON-RPC 2.0 Models
class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Dict[str, Any]] = None

class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None

def verify_function_key(code: str):
    """Verify function key like Azure Functions."""
    if API_KEY and code != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid function key")
    return True

async def execute_ha_cli_command(command: str, timeout: int = 30) -> Dict[str, Any]:
    """Execute HA CLI command using Supervisor API."""
    
    if not ENABLE_HA_CLI:
        raise Exception("HA CLI commands are disabled")
    
    # Safety validation - only allow specific safe commands
    allowed_commands = [
        "ha addons",
        "ha supervisor",
        "ha core",
        "ha host",
        "ha network",
        "ha os",
        "ha audio",
        "ha multicast",
        "ha dns",
        "ha jobs",
        "ha resolution",
        "ha info",
        "ha --help"
    ]
    
    # Check if command starts with any allowed command
    command_safe = False
    for allowed in allowed_commands:
        if command.strip().startswith(allowed):
            command_safe = True
            break
    
    if not command_safe:
        raise Exception(f"Command not allowed. Allowed commands: {', '.join(allowed_commands)}")
    
    try:
        # Check if running in Home Assistant add-on environment
        supervisor_token = os.getenv("SUPERVISOR_TOKEN")
        
        if supervisor_token:
            # Use Supervisor API when running as an add-on
            supervisor_api = SupervisorAPI()
            return await supervisor_api.execute_ha_cli_equivalent(command)
        else:
            # Fallback to shell execution (for development/testing)
            logger.warning("SUPERVISOR_TOKEN not found, falling back to shell execution")
            
            # Execute the command with timeout
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024*1024  # 1MB limit for output
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), 
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise Exception(f"Command timed out after {timeout} seconds")
            
            return {
                "command": command,
                "return_code": process.returncode,
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "success": process.returncode == 0
            }
        
    except Exception as e:
        logger.error(f"Error executing HA CLI command '{command}': {e}")
        raise Exception(f"Failed to execute command: {str(e)}")

async def handle_mcp_request(request: JsonRpcRequest) -> JsonRpcResponse:
    """Handle MCP JSON-RPC requests according to the Azure Functions pattern."""
    
    try:
        if request.method == "initialize":
            return JsonRpcResponse(
                id=request.id,
                result={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "ha-mcp-file-server",
                        "version": "1.2.0"
                    }
                }
            )
        
        elif request.method == "tools/list":
            tools = [
                {
                    "name": "list_directory",
                    "description": "List files and directories in a path",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory path to list"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "read_file",
                    "description": "Read contents of a file",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to read"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "write_file",
                    "description": "Write content to a file",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to write"},
                            "content": {"type": "string", "description": "Content to write"}
                        },
                        "required": ["path", "content"]
                    }
                },
                {
                    "name": "create_directory",
                    "description": "Create a new directory",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory path to create"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "delete_path",
                    "description": "Delete a file or directory",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path to delete"}
                        },
                        "required": ["path"]
                    }
                },
                {
                    "name": "search_files",
                    "description": "Search for files containing specific text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory to search in"},
                            "pattern": {"type": "string", "description": "Text pattern to search for"}
                        },
                        "required": ["path", "pattern"]
                    }
                },
                {
                    "name": "read_file_filtered",
                    "description": "Read file with filtering support for large files",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to read"},
                            "filter_pattern": {"type": "string", "description": "Text pattern to filter lines (case-insensitive)"},
                            "tail_lines": {"type": "integer", "description": "Number of lines from end of file to process"},
                            "max_lines": {"type": "integer", "description": "Maximum number of lines to return (default: 1000)"}
                        },
                        "required": ["path"]
                    }
                }
            ]
            
            # Add HA CLI tool if enabled
            if ENABLE_HA_CLI:
                tools.append({
                    "name": "execute_ha_cli",
                    "description": "Execute Home Assistant CLI commands safely (requires MCP_ENABLE_HA_CLI=true)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "HA CLI command to execute (e.g., 'ha addons logs core_matter_server')"},
                            "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)", "default": 30}
                        },
                        "required": ["command"]
                    }
                })
            return JsonRpcResponse(
                id=request.id,
                result={"tools": tools}
            )
        
        elif request.method == "tools/call":
            tool_name = request.params.get("name")
            arguments = request.params.get("arguments", {})
            
            if tool_name == "list_directory":
                items = await file_handler.list_directory(arguments["path"])
                result = {"content": [{"type": "text", "text": json.dumps(items, indent=2)}]}
                
            elif tool_name == "read_file":
                content = await file_handler.read_file(arguments["path"])
                result = {"content": [{"type": "text", "text": content}]}
                
            elif tool_name == "write_file":
                if READ_ONLY:
                    raise Exception("Server is in read-only mode")
                await file_handler.write_file(arguments["path"], arguments["content"])
                result = {"content": [{"type": "text", "text": f"File written successfully: {arguments['path']}"}]}
                
            elif tool_name == "create_directory":
                if READ_ONLY:
                    raise Exception("Server is in read-only mode")
                await file_handler.create_directory(arguments["path"])
                result = {"content": [{"type": "text", "text": f"Directory created: {arguments['path']}"}]}
                
            elif tool_name == "delete_path":
                if READ_ONLY:
                    raise Exception("Server is in read-only mode")
                await file_handler.delete_path(arguments["path"])
                result = {"content": [{"type": "text", "text": f"Path deleted: {arguments['path']}"}]}
                
            elif tool_name == "search_files":
                results = await file_handler.search_files(arguments["path"], arguments["pattern"])
                result = {"content": [{"type": "text", "text": json.dumps(results, indent=2)}]}
                
            elif tool_name == "read_file_filtered":
                results = await file_handler.read_file_filtered(
                    arguments["path"],
                    filter_pattern=arguments.get("filter_pattern"),
                    tail_lines=arguments.get("tail_lines"),
                    max_lines=arguments.get("max_lines", 1000)
                )
                result = {"content": [{"type": "text", "text": json.dumps(results, indent=2)}]}
                
            elif tool_name == "execute_ha_cli":
                if not ENABLE_HA_CLI:
                    raise Exception("HA CLI commands are disabled. Set MCP_ENABLE_HA_CLI=true to enable.")
                
                command_result = await execute_ha_cli_command(
                    arguments["command"],
                    timeout=arguments.get("timeout", 30)
                )
                result = {"content": [{"type": "text", "text": json.dumps(command_result, indent=2)}]}
                
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
            
            return JsonRpcResponse(id=request.id, result=result)
        
        else:
            return JsonRpcResponse(
                id=request.id,
                error={
                    "code": -32601,
                    "message": f"Method not found: {request.method}"
                }
            )
    
    except Exception as e:
        logger.error(f"Error handling MCP request: {e}")
        return JsonRpcResponse(
            id=request.id,
            error={
                "code": -32603,
                "message": str(e)
            }
        )

# GET endpoint for health check (like Azure Functions pattern)
@app.get("/api/mcp")
async def mcp_get_endpoint(code: str = Query(None)):
    """Health check endpoint like Azure Functions."""
    if API_KEY:
        verify_function_key(code)
    
    return {
        "name": "Home Assistant MCP File Server",
        "version": "1.2.0",
        "description": "File management server for Home Assistant",
        "protocol": "MCP 2024-11-05",
        "transport": "HTTP",
        "capabilities": ["tools"],
        "status": "healthy",
        "read_only": READ_ONLY,
        "allowed_dirs": ALLOWED_DIRS,
        "ha_cli_enabled": ENABLE_HA_CLI
    }

# POST endpoint for MCP requests (like Azure Functions pattern)
@app.post("/api/mcp")
async def mcp_post_endpoint(
    request: Request,
    code: str = Query(None)
):
    """
    Main MCP endpoint following Azure Functions pattern.
    Handles all JSON-RPC 2.0 MCP protocol requests.
    """
    
    # Verify function key if configured
    if API_KEY:
        verify_function_key(code)
    
    try:
        # Parse JSON-RPC request
        body = await request.json()
        
        # Handle single request or batch
        if isinstance(body, list):
            # Batch request
            responses = []
            for req_data in body:
                req = JsonRpcRequest(**req_data)
                resp = await handle_mcp_request(req)
                responses.append(resp.model_dump(exclude_none=True))
            return responses
        else:
            # Single request
            req = JsonRpcRequest(**body)
            resp = await handle_mcp_request(req)
            return resp.model_dump(exclude_none=True)
    
    except Exception as e:
        logger.error(f"Error processing MCP request: {e}")
        return {
            "jsonrpc": "2.0",
            "error": {
                "code": -32700,
                "message": "Parse error"
            }
        }

# Health check endpoint (standard)
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": "1.2.0",
        "read_only": READ_ONLY,
        "allowed_dirs": ALLOWED_DIRS,
        "ha_cli_enabled": ENABLE_HA_CLI,
        "mcp_endpoint": "/api/mcp"
    }

# CORS middleware
@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

if __name__ == "__main__":
    logger.info(f"Starting MCP File Server on port {PORT}")
    logger.info(f"MCP endpoint: http://0.0.0.0:{PORT}/api/mcp")
    logger.info(f"Read-only mode: {READ_ONLY}")
    logger.info(f"Allowed directories: {ALLOWED_DIRS}")
    logger.info(f"Function key configured: {'Yes' if API_KEY else 'No'}")
    logger.info(f"HA CLI enabled: {ENABLE_HA_CLI}")
    
    uvicorn.run(app, host="0.0.0.0", port=PORT)