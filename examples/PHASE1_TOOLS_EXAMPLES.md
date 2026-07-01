# Phase 1 Home Assistant Tools Examples

These examples assume:

- `enable_ha_cli: true`
- `read_only: false` for service/reload tools
- the service is present in `allowed_services`

## Service Calls

```text
call_service(
  domain="number",
  service="set_value",
  target={"entity_id": "number.zendure_manager_manual_power"},
  data={"value": 0}
)
```

```text
call_service(
  domain="select",
  service="select_option",
  target={"entity_id": "select.zendure_manager_mode"},
  data={"option": "off"}
)
```

```text
call_service(
  domain="homeassistant",
  service="check_config"
)
```

## Reloads

```text
reload_automations()
reload_automations(automation_id="zendure_safety_stop")
reload_scripts()
reload_template_entities()
reload_python_scripts()
reload_integration(entry_id="01JABCDEF...")
```

## Validation

```text
validate_yaml_file(path="/config/automations.yaml")
validate_automation_file(path="/config/automations/zendure.yaml")
validate_automation_file(path="/config/automations/zendure.yaml", run_check_config=true)
check_config()
```

`validate_yaml_file` warns about ambiguous values such as:

```yaml
option: off
```

Quote those values when they are meant as strings:

```yaml
option: "off"
```

## Automation Trace

```text
get_automation_trace(
  entity_id="automation.zendure_safety_stop",
  last_n=5,
  include_raw=false
)
```

Use `include_raw=true` only when the compact summary does not contain enough context.
