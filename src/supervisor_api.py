import os
import json
import logging
import aiohttp
import aiofiles
import asyncio
import pathlib
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import re

from backup_inspector import BackupLimitError, redact_sensitive_text, validate_backup_slug

logger = logging.getLogger(__name__)

class SupervisorAPI:
    """Handle communication with Home Assistant Supervisor API."""
    
    def __init__(self):
        self.base_url = "http://supervisor"
        self.token = os.getenv("SUPERVISOR_TOKEN")
        
        if not self.token:
            raise ValueError("SUPERVISOR_TOKEN environment variable not set")
        
        logger.info("SupervisorAPI initialized with Supervisor authentication")
    
    def _get_headers(self) -> Dict[str, str]:
        """Get headers for Supervisor API requests."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    async def call_supervisor_api(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        expected_statuses: Optional[List[int]] = None,
        timeout_seconds: float = 30.0,
    ) -> Any:
        """Make a direct call to the Supervisor API."""
        url = f"{self.base_url}{endpoint}"
        expected_statuses = expected_statuses or [200, 201]
        if not 0 < timeout_seconds <= 30:
            raise BackupLimitError("Supervisor API timeout is outside the hard safety range")
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            if method.upper() == "GET":
                async with session.get(url, headers=self._get_headers()) as response:
                    return await self._parse_ha_response(response, expected_statuses)
            elif method.upper() == "POST":
                async with session.post(url, headers=self._get_headers(), json=data or {}) as response:
                    return await self._parse_ha_response(response, expected_statuses)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
    
    async def get_addon_logs(self, addon_slug: str) -> str:
        """Get logs for a specific add-on."""
        url = f"{self.base_url}/addons/{addon_slug}/logs"
        
        logger.info(f"Requesting addon logs from: {url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    safe_error = redact_sensitive_text(error_text)[:2000]
                    logger.error(f"Failed to get addon logs: {response.status} - {safe_error}")
                    # Try to parse error details
                    try:
                        error_json = json.loads(error_text)
                        if 'message' in error_json:
                            raise Exception(
                                f"Failed to get addon logs: {response.status} - "
                                f"{redact_sensitive_text(error_json['message'])[:2000]}"
                            )
                    except:
                        pass
                    raise Exception(f"Failed to get addon logs: {response.status} - {safe_error}")
                
                return await response.text()
    
    async def get_addon_info(self, addon_slug: str) -> Dict[str, Any]:
        """Get information about a specific add-on."""
        url = f"{self.base_url}/addons/{addon_slug}/info"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(
                        f"Failed to get addon info: {response.status} - "
                        f"{redact_sensitive_text(error_text)[:2000]}"
                    )
                
                return await response.json()

    async def get_addon_stats(self, addon_slug: str) -> Dict[str, Any]:
        """Get runtime stats for a specific add-on."""
        return await self.call_supervisor_api("GET", f"/addons/{addon_slug}/stats")

    async def addon_action(self, addon_slug: str, action: str) -> Dict[str, Any]:
        """Run a safe Supervisor add-on action."""
        allowed_actions = {"start", "stop", "restart"}
        if action not in allowed_actions:
            raise ValueError(f"Unsupported add-on action: {action}")
        result = await self.call_supervisor_api(
            "POST",
            f"/addons/{addon_slug}/{action}",
            expected_statuses=[200, 201, 202]
        )
        return {
            "success": True,
            "addon_slug": addon_slug,
            "action": action,
            "result": result,
            "timestamp": datetime.now().isoformat()
        }
    
    async def list_addons(self) -> Dict[str, Any]:
        """List all installed add-ons."""
        url = f"{self.base_url}/addons"
        
        logger.info(f"Requesting addon list from: {url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    safe_error = redact_sensitive_text(error_text)[:2000]
                    logger.error(f"Failed to list addons: {response.status} - {safe_error}")
                    raise Exception(f"Failed to list addons: {response.status} - {safe_error}")
                
                return await response.json()

    async def list_backups(self, *, timeout_seconds: float = 30.0) -> Dict[str, Any]:
        """List Home Assistant backups, supporting current and legacy endpoints."""
        if not 0 < timeout_seconds <= 30:
            raise BackupLimitError("backup listing timeout is outside the hard safety range")
        last_error = "Supervisor did not return a backup list"
        deadline = time.monotonic() + timeout_seconds
        for endpoint in ("/backups", "/snapshots"):
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                last_error = "backup listing exceeded its time limit"
                break
            try:
                return await asyncio.wait_for(
                    self.call_supervisor_api(
                        "GET", endpoint, timeout_seconds=remaining_seconds
                    ),
                    timeout=remaining_seconds,
                )
            except asyncio.TimeoutError:
                last_error = "backup listing exceeded its time limit"
                break
            except Exception as exc:
                last_error = redact_sensitive_text(exc)
                logger.warning("Backup listing endpoint %s failed", endpoint)
        raise RuntimeError(f"Failed to list backups via Supervisor API: {last_error}")

    async def download_backup(
        self,
        slug: str,
        destination_path: str,
        *,
        max_bytes: int,
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        """Stream one backup to a controlled path with a hard byte ceiling."""
        slug = validate_backup_slug(slug)
        if not 1 <= max_bytes <= 128 * 1024 * 1024:
            raise BackupLimitError("backup download limit is outside the hard safety range")
        if not 0 < timeout_seconds <= 30:
            raise BackupLimitError("backup download timeout is outside the hard safety range")

        destination = pathlib.Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        last_error = "Supervisor did not provide the backup"
        deadline = time.monotonic() + timeout_seconds
        for endpoint in (f"/backups/{slug}/download", f"/snapshots/{slug}/download"):
            destination.unlink(missing_ok=True)
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                last_error = "backup download exceeded its time limit"
                break
            timeout = aiohttp.ClientTimeout(total=remaining_seconds)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        f"{self.base_url}{endpoint}", headers=self._get_headers()
                    ) as response:
                        if response.status != 200:
                            last_error = f"Supervisor returned HTTP {response.status}"
                            logger.warning("Backup download endpoint %s returned HTTP %s", endpoint, response.status)
                            continue

                        bytes_written = 0
                        async with aiofiles.open(destination, "wb") as output:
                            async for chunk in response.content.iter_chunked(256 * 1024):
                                bytes_written += len(chunk)
                                if bytes_written > max_bytes:
                                    raise BackupLimitError("backup download exceeded the byte limit")
                                await output.write(chunk)
                        return {
                            "success": True,
                            "slug": slug,
                            "endpoint": endpoint,
                            "bytes": bytes_written,
                        }
            except BackupLimitError:
                destination.unlink(missing_ok=True)
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                destination.unlink(missing_ok=True)
                last_error = redact_sensitive_text(exc)
                logger.warning("Backup download endpoint %s failed", endpoint)

        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download backup: {last_error}")
    
    async def get_supervisor_logs(self) -> str:
        """Get Supervisor logs."""
        url = f"{self.base_url}/supervisor/logs"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(
                        f"Failed to get supervisor logs: {response.status} - "
                        f"{redact_sensitive_text(error_text)[:2000]}"
                    )
                
                return await response.text()
    
    async def get_core_logs(self) -> str:
        """Get Home Assistant Core logs."""
        url = f"{self.base_url}/core/logs"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(
                        f"Failed to get core logs: {response.status} - "
                        f"{redact_sensitive_text(error_text)[:2000]}"
                    )
                
                return await response.text()
    
    async def get_host_logs(self) -> str:
        """Get Host logs."""
        url = f"{self.base_url}/host/logs"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(
                        f"Failed to get host logs: {response.status} - "
                        f"{redact_sensitive_text(error_text)[:2000]}"
                    )
                
                return await response.text()
    
    async def call_ha_api(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        expected_statuses: Optional[List[int]] = None
    ) -> Any:
        """Make a direct call to Home Assistant API via Supervisor proxy."""
        url = f"{self.base_url}/core/api{endpoint}"
        expected_statuses = expected_statuses or [200, 201]
        
        logger.info(f"Calling HA API: {method} {url}")
        
        async with aiohttp.ClientSession() as session:
            if method.upper() == "GET":
                async with session.get(url, headers=self._get_headers(), params=params) as response:
                    return await self._parse_ha_response(response, expected_statuses)
            elif method.upper() == "POST":
                async with session.post(url, headers=self._get_headers(), json=data, params=params) as response:
                    return await self._parse_ha_response(response, expected_statuses)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

    async def _parse_ha_response(self, response: aiohttp.ClientResponse, expected_statuses: List[int]) -> Any:
        """Parse HA API responses with consistent status and content handling."""
        response_text = await response.text()
        if response.status not in expected_statuses:
            safe_error = redact_sensitive_text(response_text)[:2000]
            logger.error(f"Failed to call HA API: {response.status} - {safe_error}")
            raise Exception(f"Failed to call HA API: {response.status} - {safe_error}")

        if not response_text:
            return {}

        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return response_text

    async def call_ha_websocket(self, command: Dict[str, Any]) -> Any:
        """Send one command to Home Assistant's WebSocket API via Supervisor proxy."""
        ws_url = f"ws://supervisor/core/websocket"
        request_id = int(command.get("id", 1))
        payload = dict(command)
        payload["id"] = request_id

        logger.info(f"Calling HA WebSocket command: {payload.get('type')}")

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, headers=self._get_headers()) as ws:
                auth_required = await ws.receive_json()
                if auth_required.get("type") != "auth_required":
                    raise Exception(f"Expected auth_required, got: {auth_required}")

                await ws.send_json({
                    "type": "auth",
                    "access_token": self.token
                })

                auth_response = await ws.receive_json()
                if auth_response.get("type") != "auth_ok":
                    raise Exception(f"Authentication failed: {auth_response}")

                await ws.send_json(payload)

                while True:
                    response = await ws.receive_json()
                    if response.get("id") != request_id:
                        continue

                    if not response.get("success", False):
                        error = response.get("error") or response
                        raise Exception(f"Home Assistant WebSocket command failed: {error}")

                    return response.get("result", {})

    async def call_service(
        self,
        domain: str,
        service: str,
        target: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        return_response: bool = False
    ) -> Dict[str, Any]:
        """Call a Home Assistant service through the WebSocket API."""
        command = {
            "type": "call_service",
            "domain": domain,
            "service": service,
            "target": target or {},
            "service_data": data or {},
            "return_response": return_response,
        }
        response = await self.call_ha_websocket(command)
        context = response.get("context", {}) if isinstance(response, dict) else {}

        return {
            "success": True,
            "domain": domain,
            "service": service,
            "context_id": context.get("id"),
            "response": response.get("response") if isinstance(response, dict) else response,
            "error": None,
        }

    async def check_config(self) -> Dict[str, Any]:
        """Run Home Assistant's core config check."""
        result = await self.call_ha_api("POST", "/config/core/check_config", data={})
        return {
            "success": True,
            "result": result,
            "timestamp": datetime.now().isoformat()
        }

    async def get_state(self, entity_id: str) -> Dict[str, Any]:
        """Get the current state for one entity."""
        state = await self.call_ha_api("GET", f"/states/{entity_id}")
        return {
            "entity_id": entity_id,
            "state": state,
            "timestamp": datetime.now().isoformat()
        }

    async def get_states(
        self,
        entity_ids: List[str],
        attributes: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Get a compact current-state snapshot for multiple entities."""
        if not entity_ids:
            raise ValueError("entity_ids must contain at least one entity_id")

        states = await self.call_ha_api("GET", "/states")
        state_by_entity_id = {
            state.get("entity_id"): state
            for state in states
            if isinstance(state, dict) and state.get("entity_id")
        }

        snapshot = []
        missing = []
        for entity_id in entity_ids:
            state = state_by_entity_id.get(entity_id)
            if not state:
                missing.append(entity_id)
                snapshot.append({
                    "entity_id": entity_id,
                    "found": False,
                    "error": "Entity not found"
                })
                continue

            entity_attributes = state.get("attributes", {})
            if attributes:
                entity_attributes = {
                    key: entity_attributes.get(key)
                    for key in attributes
                    if key in entity_attributes
                }

            snapshot.append({
                "entity_id": entity_id,
                "found": True,
                "state": state.get("state"),
                "last_changed": state.get("last_changed"),
                "last_updated": state.get("last_updated"),
                "attributes": entity_attributes,
            })

        return {
            "timestamp": datetime.now().isoformat(),
            "requested_count": len(entity_ids),
            "returned_count": len(snapshot),
            "missing_count": len(missing),
            "missing": missing,
            "states": snapshot,
        }

    async def list_traces(self, domain: str, item_id: str) -> Any:
        """List stored traces for an automation/script item."""
        return await self.call_ha_websocket({
            "type": "trace/list",
            "domain": domain,
            "item_id": item_id
        })

    async def get_trace(self, domain: str, item_id: str, run_id: str) -> Any:
        """Get one stored trace for an automation/script item."""
        return await self.call_ha_websocket({
            "type": "trace/get",
            "domain": domain,
            "item_id": item_id,
            "run_id": run_id
        })
    
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
            entities = await self.call_ha_websocket({
                "type": "config/entity_registry/list"
            })
            
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
        minimal_change: Optional[float] = None,
        unavailable_transitions_only: bool = False
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
            start_str = start_dt.isoformat()
            end_str = end_dt.isoformat()
            
            # Make API call to get history
            endpoint = f"/history/period/{start_str}"
            params = {
                "filter_entity_id": entity_id,
                "end_time": end_str
            }
            
            logger.info(f"Requesting entity history: {entity_id} from {start_str} to {end_str}")
            
            history_raw = await self.call_ha_api("GET", endpoint, params=params)
            
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
                limit=limit,
                unavailable_transitions_only=unavailable_transitions_only
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
                    "unavailable_transitions_only": unavailable_transitions_only,
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

    async def get_ha_entities_history(
        self,
        entity_ids: List[str],
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit_per_entity: int = 1000,
        minimal_change: Optional[float] = None,
        unavailable_transitions_only: bool = False,
        include_state_changes: bool = False,
        include_timeline: bool = True,
        timeline_limit: int = 1000
    ) -> Dict[str, Any]:
        """Get historical summaries for multiple Home Assistant entities."""
        if not entity_ids:
            raise ValueError("entity_ids must contain at least one entity_id")

        start_dt, end_dt = self._parse_time_parameters(start_time, end_time)
        start_str = start_dt.isoformat()
        end_str = end_dt.isoformat()
        params = {
            "filter_entity_id": ",".join(entity_ids),
            "end_time": end_str
        }

        logger.info(f"Requesting multi-entity history for {len(entity_ids)} entities from {start_str} to {end_str}")
        history_raw = await self.call_ha_api("GET", f"/history/period/{start_str}", params=params)

        raw_by_entity = {entity_id: [] for entity_id in entity_ids}
        if isinstance(history_raw, list):
            for entity_states in history_raw:
                if not isinstance(entity_states, list) or not entity_states:
                    continue
                entity_id = entity_states[0].get("entity_id")
                if entity_id in raw_by_entity:
                    raw_by_entity[entity_id] = entity_states

        entities = []
        combined_timeline = []
        total_changes = 0
        unavailable_total_seconds = 0.0
        unavailable_entity_count = 0

        for entity_id in entity_ids:
            raw_states = raw_by_entity.get(entity_id, [])
            processed_changes = self._process_state_changes(
                raw_states,
                minimal_change=minimal_change,
                limit=limit_per_entity,
                unavailable_transitions_only=unavailable_transitions_only
            )
            statistics = self._calculate_statistics(processed_changes, start_dt, end_dt)
            availability = self._calculate_unavailable_periods(raw_states, end_dt)

            total_changes += len(processed_changes)
            unavailable_total_seconds += availability["total_unavailable_seconds"]
            if availability["period_count"]:
                unavailable_entity_count += 1

            entity_summary = {
                "entity_id": entity_id,
                "found": bool(raw_states),
                "raw_change_count": len(raw_states),
                "returned_change_count": len(processed_changes),
                "statistics": statistics,
                "availability": availability,
            }
            if processed_changes:
                entity_summary["first_state"] = processed_changes[0].get("state")
                entity_summary["last_state"] = processed_changes[-1].get("state")
                entity_summary["last_changed"] = processed_changes[-1].get("timestamp")
            if include_state_changes:
                entity_summary["state_changes"] = processed_changes

            entities.append(entity_summary)

            if include_timeline:
                for change in processed_changes:
                    combined_timeline.append({
                        "entity_id": entity_id,
                        "timestamp": change.get("timestamp"),
                        "timestamp_local": change.get("timestamp_local"),
                        "from_state": change.get("from_state"),
                        "state": change.get("state"),
                        "context_id": change.get("context_id"),
                    })

        if include_timeline:
            combined_timeline.sort(key=lambda item: item.get("timestamp") or "")
            if timeline_limit >= 0:
                combined_timeline = combined_timeline[:timeline_limit]

        return {
            "entity_ids": entity_ids,
            "query_period": {
                "start": start_str,
                "end": end_str,
                "duration_hours": (end_dt - start_dt).total_seconds() / 3600
            },
            "entities": entities,
            "summary": {
                "entity_count": len(entity_ids),
                "entities_with_history": sum(1 for item in entities if item["found"]),
                "total_returned_changes": total_changes,
                "unavailable_entity_count": unavailable_entity_count,
                "total_unavailable_seconds": unavailable_total_seconds,
                "total_unavailable_minutes": unavailable_total_seconds / 60,
            },
            "timeline": combined_timeline if include_timeline else None,
            "query_metadata": {
                "limit_per_entity": limit_per_entity,
                "minimal_change_filter": minimal_change,
                "unavailable_transitions_only": unavailable_transitions_only,
                "include_state_changes": include_state_changes,
                "include_timeline": include_timeline,
                "timeline_limit": timeline_limit,
                "timestamp": datetime.now().isoformat()
            }
        }

    def _parse_time_parameters(self, start_time: Optional[str], end_time: Optional[str]) -> tuple:
        """Parse start and end time parameters into datetime objects."""
        now = datetime.now().astimezone()
        
        # Parse end time
        if not end_time or end_time.lower() == "now":
            end_dt = now
        else:
            try:
                # Try parsing as ISO format
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.astimezone()
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
                if start_dt.tzinfo is None:
                    start_dt = start_dt.astimezone()
            except ValueError:
                raise ValueError(f"Invalid start_time format: {start_time}")
        
        # Validate time range
        if start_dt >= end_dt:
            raise ValueError("start_time must be before end_time")
        
        return start_dt, end_dt

    def _parse_relative_time(self, relative_str: str, reference_time: datetime) -> datetime:
        """Parse relative time strings like '-30m', '-6h', '-24h', '-7d'."""
        match = re.match(r"^-(\d+)([mhdw])$", relative_str.lower())
        if not match:
            raise ValueError(f"Invalid relative time format: {relative_str}")
        
        amount, unit = match.groups()
        amount = int(amount)
        
        if unit == "m":
            return reference_time - timedelta(minutes=amount)
        elif unit == "h":
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
        limit: int = 1000,
        unavailable_transitions_only: bool = False
    ) -> list:
        """Process and filter raw state changes from Home Assistant history."""
        if not raw_states:
            return []
        
        processed = []
        previous_numeric_value = None
        previous_state = None
        
        for state_obj in raw_states:
            try:
                current_state = state_obj.get("state")
                transitioned_unavailable = (
                    current_state == "unavailable" or previous_state == "unavailable"
                )
                from_state = previous_state
                previous_state = current_state

                if unavailable_transitions_only and not transitioned_unavailable:
                    continue

                state_info = {
                    "timestamp": state_obj.get("last_changed"),
                    "timestamp_local": self._format_local_timestamp(state_obj.get("last_changed")),
                    "last_updated": state_obj.get("last_updated"),
                    "last_updated_local": self._format_local_timestamp(state_obj.get("last_updated")),
                    "from_state": from_state,
                    "state": current_state,
                    "context_id": state_obj.get("context", {}).get("id") if isinstance(state_obj.get("context"), dict) else None,
                    "parent_id": state_obj.get("context", {}).get("parent_id") if isinstance(state_obj.get("context"), dict) else None,
                    "attributes": state_obj.get("attributes", {})
                }
                
                # Add friendly name if available
                if "friendly_name" in state_obj.get("attributes", {}):
                    state_info["friendly_name"] = state_obj["attributes"]["friendly_name"]
                
                # Add unit of measurement if available
                if "unit_of_measurement" in state_obj.get("attributes", {}):
                    state_info["unit"] = state_obj["attributes"]["unit_of_measurement"]
                
                try:
                    numeric_value = float(state_obj.get("state", 0))

                    if minimal_change is not None and previous_numeric_value is not None:
                        change = abs(numeric_value - previous_numeric_value)
                        if change < minimal_change:
                            continue

                    state_info["numeric_value"] = numeric_value
                    previous_numeric_value = numeric_value

                except (ValueError, TypeError):
                    # Not a numeric sensor, include all changes.
                    pass
                
                processed.append(state_info)
                if len(processed) >= limit:
                    break
                
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

    def _format_local_timestamp(self, timestamp: Optional[str]) -> Optional[str]:
        """Convert HA timestamps to local ISO timestamps when possible."""
        if not timestamp:
            return None
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return parsed.astimezone().isoformat()
        except (ValueError, TypeError):
            return None

    def _parse_ha_timestamp(self, timestamp: Optional[str]) -> Optional[datetime]:
        """Parse a Home Assistant timestamp into an aware datetime."""
        if not timestamp:
            return None
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return parsed.astimezone() if parsed.tzinfo else parsed.astimezone()
        except (ValueError, TypeError):
            return None

    def _calculate_unavailable_periods(self, raw_states: list, end_time: datetime) -> Dict[str, Any]:
        """Calculate periods where an entity was unavailable."""
        periods = []
        current_start = None
        previous_state = None

        for state_obj in raw_states or []:
            state = state_obj.get("state")
            timestamp = self._parse_ha_timestamp(state_obj.get("last_changed"))
            if not timestamp:
                previous_state = state
                continue

            if state == "unavailable" and previous_state != "unavailable":
                current_start = timestamp
            elif previous_state == "unavailable" and state != "unavailable" and current_start:
                duration_seconds = (timestamp - current_start).total_seconds()
                periods.append({
                    "start": current_start.isoformat(),
                    "end": timestamp.isoformat(),
                    "duration_seconds": max(duration_seconds, 0),
                    "open": False,
                })
                current_start = None

            previous_state = state

        if previous_state == "unavailable" and current_start:
            end_dt = end_time.astimezone() if end_time.tzinfo else end_time.astimezone()
            duration_seconds = (end_dt - current_start).total_seconds()
            periods.append({
                "start": current_start.isoformat(),
                "end": end_dt.isoformat(),
                "duration_seconds": max(duration_seconds, 0),
                "open": True,
            })

        total_seconds = sum(period["duration_seconds"] for period in periods)
        return {
            "period_count": len(periods),
            "total_unavailable_seconds": total_seconds,
            "total_unavailable_minutes": total_seconds / 60,
            "periods": periods,
        }
    
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
            if parts[1] == "addons" and len(parts) == 4 and parts[2] == "logs":
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
            
            elif parts[1] == "addons" and len(parts) == 4 and parts[2] == "info":
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
            
            elif parts[1] == "supervisor" and len(parts) == 3 and parts[2] == "logs":
                # ha supervisor logs
                logs = await self.get_supervisor_logs()
                return {
                    "command": command,
                    "return_code": 0,
                    "stdout": logs,
                    "stderr": "",
                    "success": True
                }
            
            elif parts[1] == "core" and len(parts) == 3 and parts[2] == "logs":
                # ha core logs
                logs = await self.get_core_logs()
                return {
                    "command": command,
                    "return_code": 0,
                    "stdout": logs,
                    "stderr": "",
                    "success": True
                }
            
            elif parts[1] == "host" and len(parts) == 3 and parts[2] == "logs":
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
                "stderr": redact_sensitive_text(e),
                "success": False
            }
