#!/usr/bin/env python3
"""
Test script for Home Assistant CLI functionality in MCP File Server.

This script demonstrates how to use the HA CLI commands through the MCP server.
It requires the MCP server to be running with ENABLE_HA_CLI=true.
"""

import json
import requests
import sys

def test_mcp_request(url, command, timeout=30):
    """Send a JSON-RPC request to test HA CLI command execution."""
    
    request_data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "execute_ha_cli",
            "arguments": {
                "command": command,
                "timeout": timeout
            }
        }
    }
    
    try:
        response = requests.post(url, json=request_data, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Request failed: {e}"}

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_ha_cli.py <mcp_server_url> [ha_command]")
        print("Example: python test_ha_cli.py http://homeassistant.local:6789/api/mcp 'ha info'")
        sys.exit(1)
    
    mcp_url = sys.argv[1]
    ha_command = sys.argv[2] if len(sys.argv) > 2 else "ha info"
    
    print(f"Testing HA CLI command: {ha_command}")
    print(f"MCP Server URL: {mcp_url}")
    print("-" * 50)
    
    # Test the HA CLI command
    result = test_mcp_request(mcp_url, ha_command)
    
    if "error" in result:
        print(f"❌ Error: {result['error']}")
        if "message" in result.get("error", {}):
            print(f"Details: {result['error']['message']}")
    elif "result" in result:
        content = result["result"]["content"][0]["text"]
        command_result = json.loads(content)
        
        print(f"✅ Command executed successfully")
        print(f"Return code: {command_result['return_code']}")
        print(f"Success: {command_result['success']}")
        print("\n📤 STDOUT:")
        print(command_result['stdout'])
        
        if command_result['stderr']:
            print("\n📥 STDERR:")
            print(command_result['stderr'])
    else:
        print(f"❓ Unexpected response: {result}")

if __name__ == "__main__":
    main()