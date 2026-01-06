import os
import json
import logging
import aiohttp
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import re

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

    async def get_ha_entity_history(
        self,
        entity_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 1000,
        minimal_change: Optional[float] = None
    ) -> Dict[str, Any]:
        """Get historical state changes for a Home Assistant entity.
        
        Args:
            entity_id: Target entity ID (e.g., 'sensor.temperature')
            start_time: Start time in ISO 8601 format or relative format ('-6h', '-24h', '-7d')
            end_time: End time in ISO 8601 format or 'now'
            limit: Maximum number of state changes to return
            minimal_change: For numeric sensors, filter out changes smaller than this value
            
        Returns:
            Dict containing historical state changes with timestamps, statistics, and metadata
        """
        try:
            # Parse and validate time parameters
            start_dt, end_dt = self._parse_time_parameters(start_time, end_time)
            
            # Format timestamps for Home Assistant API
            start_str = start_dt.isoformat() + "Z"
            end_str = end_dt.isoformat() + "Z"
            
            # Make API call to get history
            endpoint = f"/history/period/{start_str}"
            params = {
                "filter_entity_id": entity_id,
                "end_time": end_str
            }
            
            # Build URL with query parameters
            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            full_endpoint = f"{endpoint}?{query_string}"
            
            logger.info(f"Requesting entity history: {entity_id} from {start_str} to {end_str}")
            
            history_raw = await self.call_ha_api("GET", full_endpoint)
            
            # Process the history data
            if not history_raw or not isinstance(history_raw, list) or len(history_raw) == 0:
                return {
                    "entity_id": entity_id,
                    "query_period": {
                        "start": start_str,
                        "end": end_str
                    },
                    "total_changes": 0,
                    "state_changes": [],
                    "statistics": None,
                    "error": "No historical data found for the specified period"
                }
            
            # Extract state changes from the nested structure
            entity_states = history_raw[0] if len(history_raw) > 0 else []
            
            # Process and filter state changes
            processed_changes = self._process_state_changes(
                entity_states, 
                minimal_change=minimal_change,
                limit=limit
            )
            
            # Calculate statistics for numeric sensors
            statistics = self._calculate_statistics(processed_changes, start_dt, end_dt)
            
            # Prepare response
            result = {
                "entity_id": entity_id,
                "query_period": {
                    "start": start_str,
                    "end": end_str,
                    "duration_hours": (end_dt - start_dt).total_seconds() / 3600
                },
                "total_changes": len(processed_changes),
                "state_changes": processed_changes,
                "statistics": statistics,
                "query_metadata": {
                    "limit_applied": limit,
                    "minimal_change_filter": minimal_change,
                    "timestamp": datetime.now().isoformat()
                }
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting entity history for {entity_id}: {e}")
            return {
                "entity_id": entity_id,
                "error": f"Failed to retrieve history: {str(e)}",
                "query_period": {
                    "start": start_time or "12 hours ago",
                    "end": end_time or "now"
                },
                "total_changes": 0,
                "state_changes": [],
                "statistics": None
            }

    def _parse_time_parameters(self, start_time: Optional[str], end_time: Optional[str]) -> tuple:
        """Parse start and end time parameters into datetime objects."""
        now = datetime.now()
        
        # Parse end time
        if not end_time or end_time.lower() == "now":
            end_dt = now
        else:
            try:
                # Try parsing as ISO format
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(f"Invalid end_time format: {end_time}")
        
        # Parse start time
        if not start_time:
            # Default to 12 hours ago
            start_dt = now - timedelta(hours=12)
        elif start_time.startswith("-"):
            # Relative format like "-6h", "-24h", "-7d"
            start_dt = self._parse_relative_time(start_time, now)
        else:
            try:
                # Try parsing as ISO format
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(f"Invalid start_time format: {start_time}")
        
        # Validate time range
        if start_dt >= end_dt:
            raise ValueError("start_time must be before end_time")
        
        return start_dt, end_dt

    def _parse_relative_time(self, relative_str: str, reference_time: datetime) -> datetime:
        """Parse relative time strings like '-6h', '-24h', '-7d'."""
        match = re.match(r"^-(\d+)([hdw])$", relative_str.lower())
        if not match:
            raise ValueError(f"Invalid relative time format: {relative_str}")
        
        amount, unit = match.groups()
        amount = int(amount)
        
        if unit == "h":
            return reference_time - timedelta(hours=amount)
        elif unit == "d":
            return reference_time - timedelta(days=amount)
        elif unit == "w":
            return reference_time - timedelta(weeks=amount)
        else:
            raise ValueError(f"Unsupported time unit: {unit}")

    def _process_state_changes(
        self, 
        raw_states: list, 
        minimal_change: Optional[float] = None, 
        limit: int = 1000
    ) -> list:
        """Process and filter raw state changes from Home Assistant history."""
        if not raw_states:
            return []
        
        processed = []
        previous_numeric_value = None
        
        for state_obj in raw_states[:limit]:  # Apply limit early
            try:
                state_info = {
                    "timestamp": state_obj.get("last_changed"),
                    "state": state_obj.get("state"),
                    "attributes": state_obj.get("attributes", {})
                }
                
                # Add friendly name if available
                if "friendly_name" in state_obj.get("attributes", {}):
                    state_info["friendly_name"] = state_obj["attributes"]["friendly_name"]
                
                # Add unit of measurement if available
                if "unit_of_measurement" in state_obj.get("attributes", {}):
                    state_info["unit"] = state_obj["attributes"]["unit_of_measurement"]
                
                # Apply minimal change filter for numeric values
                if minimal_change is not None:
                    try:
                        numeric_value = float(state_obj.get("state", 0))
                        
                        if previous_numeric_value is not None:
                            change = abs(numeric_value - previous_numeric_value)
                            if change < minimal_change:
                                continue  # Skip this state change
                        
                        state_info["numeric_value"] = numeric_value
                        previous_numeric_value = numeric_value
                        
                    except (ValueError, TypeError):
                        # Not a numeric sensor, include all changes
                        pass
                
                processed.append(state_info)
                
            except Exception as e:
                logger.warning(f"Error processing state change: {e}")
                continue
        
        return processed

    def _calculate_statistics(
        self, 
        state_changes: list, 
        start_time: datetime, 
        end_time: datetime
    ) -> Optional[Dict[str, Any]]:
        """Calculate statistics for numeric sensor data."""
        if not state_changes:
            return None
        
        # Extract numeric values
        numeric_values = []
        for change in state_changes:
            if "numeric_value" in change:
                numeric_values.append(change["numeric_value"])
        
        if not numeric_values:
            return {
                "type": "non_numeric",
                "total_changes": len(state_changes),
                "time_period_hours": (end_time - start_time).total_seconds() / 3600,
                "changes_per_hour": len(state_changes) / max((end_time - start_time).total_seconds() / 3600, 1)
            }
        
        # Calculate numeric statistics
        duration_hours = (end_time - start_time).total_seconds() / 3600
        
        statistics = {
            "type": "numeric",
            "total_changes": len(state_changes),
            "numeric_changes": len(numeric_values),
            "time_period_hours": duration_hours,
            "changes_per_hour": len(state_changes) / max(duration_hours, 1),
            "value_statistics": {
                "min": min(numeric_values),
                "max": max(numeric_values),
                "average": sum(numeric_values) / len(numeric_values),
                "first_value": numeric_values[0],
                "last_value": numeric_values[-1],
                "total_variation": max(numeric_values) - min(numeric_values)
            }
        }
        
        # Add unit if available
        if state_changes and "unit" in state_changes[0]:
            statistics["unit"] = state_changes[0]["unit"]
        
        return statistics
    
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