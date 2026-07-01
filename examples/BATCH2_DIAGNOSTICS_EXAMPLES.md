# Batch 2 Diagnostics Examples

These examples cover the second wishlist batch: focused log queries, current state snapshots, MCP add-on management, and better history/statistics queries.

## Log Queries

`query_logs` works as a file diagnostic tool and does not require `enable_ha_cli`. The log path must still be inside `allowed_dirs`.

```text
query_logs(
  path="/config/home-assistant.log",
  since="-30m",
  level=["ERROR", "WARNING"],
  limit=25
)
```

```text
query_logs(
  logger_filter="custom_components.zendure",
  text_filter=["battery", "unavailable"],
  match_mode="all",
  since="-90m"
)
```

```text
query_logs(
  text_filter="Traceback",
  max_bytes=1048576,
  limit=10
)
```

## Live State Snapshot

`get_states` requires `enable_ha_cli: true` because it reads Home Assistant state through the REST API.

```text
get_states(
  entity_ids=[
    "sensor.battery_power",
    "sensor.battery_state_of_charge",
    "number.zendure_manager_manual_power"
  ],
  attributes=["friendly_name", "unit_of_measurement"]
)
```

## Entity History

History windows now support minutes, so short debugging sessions can stay small and fast.

```text
get_ha_entity_history(
  entity_id="sensor.battery_power",
  start_time="-90m",
  limit=200,
  minimal_change=5
)
```

To diagnose entity availability issues:

```text
get_ha_entity_history(
  entity_id="sensor.battery_power",
  start_time="-24h",
  unavailable_transitions_only=true
)
```

For SMA/Zendure-style analysis across several related entities:

```text
get_ha_entities_history(
  entity_ids=[
    "sensor.sma_power",
    "sensor.zendure_power",
    "sensor.zendure_state_of_charge",
    "number.zendure_manager_manual_power"
  ],
  start_time="-90m",
  include_timeline=true,
  include_state_changes=false,
  timeline_limit=300
)
```

This returns per-entity statistics, unavailable periods, and a combined timeline sorted by timestamp.

## MCP Add-on Management

Check whether the running container really has HA tools enabled:

```text
get_mcp_runtime_status()
```

Inspect the add-on state/config/options and include recent logs:

```text
get_mcp_addon_info(include_logs=true, log_lines=100)
```

Read only the add-on logs:

```text
get_mcp_addon_logs(lines=200)
```

Restart the MCP add-on itself:

```text
restart_mcp_addon()
```

`restart_mcp_addon` requires `enable_ha_cli: true` and `read_only: false`. The MCP connection can drop while Supervisor restarts the container.
