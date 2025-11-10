import os
import json
import logging
import aiohttp
import asyncio
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
    
    async def call_ha_api(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a direct call to Home Assistant API via Supervisor proxy."""
        url = f"{self.base_url}/core/api{endpoint}"
        
        logger.info(f"Calling HA API: {method} {url}")
        
        async with aiohttp.ClientSession() as session:
            if method.upper() == "GET":
                async with session.get(url, headers=self._get_headers()) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Failed to call HA API: {response.status} - {error_text}")
                        raise Exception(f"Failed to call HA API: {response.status} - {error_text}")
                    
                    return await response.json()
            elif method.upper() == "POST":
                async with session.post(url, headers=self._get_headers(), json=data) as response:
                    if response.status not in [200, 201]:
                        error_text = await response.text()
                        logger.error(f"Failed to call HA API: {response.status} - {error_text}")
                        raise Exception(f"Failed to call HA API: {response.status} - {error_text}")
                    
                    return await response.json()
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
    
    async def get_ha_entities(self) -> Dict[str, Any]:
        """Get all Home Assistant entities (states)."""
        try:
            entities = await self.call_ha_api("GET", "/states")
            return {
                "entities": entities,
                "count": len(entities) if entities else 0,
                "timestamp": "now"
            }
        except Exception as e:
            logger.error(f"Error getting HA entities: {e}")
            raise Exception(f"Failed to get entities: {str(e)}")
    
    async def get_ha_devices(self) -> Dict[str, Any]:
        """Get all Home Assistant devices from device registry."""
        try:
            # Note: This endpoint might require admin privileges
            devices = await self.call_ha_api("GET", "/config/device_registry/list")
            return {
                "devices": devices,
                "count": len(devices) if devices else 0,
                "timestamp": "now"
            }
        except Exception as e:
            logger.error(f"Error getting HA devices: {e}")
            # Fallback: try alternative approach or return partial info
            raise Exception(f"Failed to get devices: {str(e)}")
    
    async def get_ha_entity_registry(self) -> Dict[str, Any]:
        """Get all Home Assistant entities from entity registry.
        
        This is the most efficient way to get all entities with platform information,
        unique_id, and other registry metadata. Particularly useful for filtering
        entities by platform (e.g., mqtt, zwave, zigbee).
        
        Uses WebSocket API to access the entity registry.
        
        Returns:
            Dict containing:
            - entities: List of entity registry entries with entity_id, platform, unique_id, etc.
            - count: Number of entities
            - timestamp: Current timestamp
        """
        try:
            # Entity registry is only accessible via WebSocket API
            # We'll use the supervisor proxy to connect to the websocket
            ws_url = f"ws://supervisor/core/websocket"
            
            logger.info(f"Connecting to HA WebSocket: {ws_url}")
            
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url, headers=self._get_headers()) as ws:
                    # Wait for auth_required message
                    msg = await ws.receive_json()
                    logger.debug(f"Received: {msg}")
                    
                    if msg.get("type") != "auth_required":
                        raise Exception(f"Expected auth_required, got: {msg}")
                    
                    # Send auth message with supervisor token
                    await ws.send_json({
                        "type": "auth",
                        "access_token": self.token
                    })
                    
                    # Wait for auth_ok
                    auth_response = await ws.receive_json()
                    logger.debug(f"Auth response: {auth_response}")
                    
                    if auth_response.get("type") != "auth_ok":
                        raise Exception(f"Authentication failed: {auth_response}")
                    
                    # Request entity registry list
                    request_id = 1
                    await ws.send_json({
                        "id": request_id,
                        "type": "config/entity_registry/list"
                    })
                    
                    # Wait for response
                    response = await ws.receive_json()
                    logger.debug(f"Entity registry response received")
                    
                    if not response.get("success"):
                        raise Exception(f"Failed to get entity registry: {response}")
                    
                    entities = response.get("result", [])
                    
                    await ws.close()
                    
                    return {
                        "entities": entities,
                        "count": len(entities),
                        "timestamp": "now"
                    }
                    
        except Exception as e:
            logger.error(f"Error getting HA entity registry via WebSocket: {e}")
            logger.info("Falling back to states endpoint with enhanced information")
            
            try:
                # Fallback: get entities via states endpoint
                states = await self.get_ha_entities()
                
                # Convert states to registry-like format
                entities_from_states = []
                for entity in states.get("entities", []):
                    entities_from_states.append({
                        "entity_id": entity.get("entity_id"),
                        "state": entity.get("state"),
                        "attributes": entity.get("attributes", {}),
                        "last_changed": entity.get("last_changed"),
                        "platform": entity.get("attributes", {}).get("device_class", "unknown"),
                        "note": "Limited data - using states endpoint fallback"
                    })
                
                return {
                    "entities": entities_from_states,
                    "count": len(entities_from_states),
                    "timestamp": "now",
                    "fallback_mode": True,
                    "note": "Entity registry accessed via states endpoint (limited data)"
                }
            except Exception as fallback_error:
                logger.error(f"Fallback also failed: {fallback_error}")
                raise Exception(f"Failed to get entity registry: {str(e)}")
    
    async def get_ha_services(self) -> Dict[str, Any]:
        """Get all Home Assistant services."""
        try:
            services = await self.call_ha_api("GET", "/services")
            return {
                "services": services,
                "timestamp": "now"
            }
        except Exception as e:
            logger.error(f"Error getting HA services: {e}")
            raise Exception(f"Failed to get services: {str(e)}")
    
    async def get_ha_config(self) -> Dict[str, Any]:
        """Get Home Assistant configuration info."""
        try:
            config = await self.call_ha_api("GET", "/config")
            return {
                "config": config,
                "timestamp": "now"
            }
        except Exception as e:
            logger.error(f"Error getting HA config: {e}")
            raise Exception(f"Failed to get config: {str(e)}")
    
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