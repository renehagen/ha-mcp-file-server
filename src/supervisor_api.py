import os
import json
import logging
import aiohttp
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class SupervisorAPI:
    """Handle communication with Home Assistant Supervisor API."""
    
    def __init__(self):
        self.base_url = "http://supervisor"
        self.token = os.getenv("SUPERVISOR_TOKEN")
        
        if not self.token:
            raise ValueError("SUPERVISOR_TOKEN environment variable not set")
        
        logger.info(f"SupervisorAPI initialized with token: {self.token[:10]}...")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Supervisor API requests."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
    
    async def get_addon_logs(self, addon_slug: str) -> str:
        """Get logs for a specific add-on."""
        url = f"{self.base_url}/addons/{addon_slug}/logs"
        
        logger.info(f"Requesting addon logs from: {url}")
        logger.debug(f"Using headers: {self._get_headers()}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to get addon logs: {response.status} - {error_text}")
                    # Try to parse error details
                    try:
                        error_json = json.loads(error_text)
                        if 'message' in error_json:
                            raise Exception(f"Failed to get addon logs: {response.status} - {error_json['message']}")
                    except:
                        pass
                    raise Exception(f"Failed to get addon logs: {response.status} - {error_text}")
                
                return await response.text()
    
    async def get_addon_info(self, addon_slug: str) -> Dict[str, Any]:
        """Get information about a specific add-on."""
        url = f"{self.base_url}/addons/{addon_slug}/info"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Failed to get addon info: {response.status} - {error_text}")
                
                return await response.json()
    
    async def list_addons(self) -> Dict[str, Any]:
        """List all installed add-ons."""
        url = f"{self.base_url}/addons"
        
        logger.info(f"Requesting addon list from: {url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to list addons: {response.status} - {error_text}")
                    raise Exception(f"Failed to list addons: {response.status} - {error_text}")
                
                return await response.json()
    
    async def get_supervisor_logs(self) -> str:
        """Get Supervisor logs."""
        url = f"{self.base_url}/supervisor/logs"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Failed to get supervisor logs: {response.status} - {error_text}")
                
                return await response.text()
    
    async def get_core_logs(self) -> str:
        """Get Home Assistant Core logs."""
        url = f"{self.base_url}/core/logs"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Failed to get core logs: {response.status} - {error_text}")
                
                return await response.text()
    
    async def get_host_logs(self) -> str:
        """Get Host logs."""
        url = f"{self.base_url}/host/logs"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Failed to get host logs: {response.status} - {error_text}")
                
                return await response.text()
    
    async def execute_ha_cli_equivalent(self, command: str) -> Dict[str, Any]:
        """Execute equivalent of HA CLI commands using Supervisor API."""
        
        # Parse the command to determine what API to call
        parts = command.strip().split()
        
        if len(parts) < 2 or parts[0] != "ha":
            raise ValueError(f"Invalid command format: {command}")
        
        try:
            if parts[1] == "addons" and len(parts) >= 4 and parts[2] == "logs":
                # ha addons logs <addon_slug>
                addon_slug = parts[3]
                logs = await self.get_addon_logs(addon_slug)
                return {
                    "command": command,
                    "return_code": 0,
                    "stdout": logs,
                    "stderr": "",
                    "success": True
                }
            
            elif parts[1] == "addons" and len(parts) >= 4 and parts[2] == "info":
                # ha addons info <addon_slug>
                addon_slug = parts[3]
                info = await self.get_addon_info(addon_slug)
                return {
                    "command": command,
                    "return_code": 0,
                    "stdout": json.dumps(info, indent=2),
                    "stderr": "",
                    "success": True
                }
            
            elif parts[1] == "addons" and len(parts) == 2:
                # ha addons (list)
                addons = await self.list_addons()
                return {
                    "command": command,
                    "return_code": 0,
                    "stdout": json.dumps(addons, indent=2),
                    "stderr": "",
                    "success": True
                }
            
            elif parts[1] == "supervisor" and len(parts) >= 3 and parts[2] == "logs":
                # ha supervisor logs
                logs = await self.get_supervisor_logs()
                return {
                    "command": command,
                    "return_code": 0,
                    "stdout": logs,
                    "stderr": "",
                    "success": True
                }
            
            elif parts[1] == "core" and len(parts) >= 3 and parts[2] == "logs":
                # ha core logs
                logs = await self.get_core_logs()
                return {
                    "command": command,
                    "return_code": 0,
                    "stdout": logs,
                    "stderr": "",
                    "success": True
                }
            
            elif parts[1] == "host" and len(parts) >= 3 and parts[2] == "logs":
                # ha host logs
                logs = await self.get_host_logs()
                return {
                    "command": command,
                    "return_code": 0,
                    "stdout": logs,
                    "stderr": "",
                    "success": True
                }
            
            else:
                raise ValueError(f"Unsupported HA CLI command: {command}")
                
        except Exception as e:
            return {
                "command": command,
                "return_code": 1,
                "stdout": "",
                "stderr": str(e),
                "success": False
            }