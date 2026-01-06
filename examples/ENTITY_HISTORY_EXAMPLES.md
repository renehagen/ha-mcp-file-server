# Home Assistant Entity History Examples

This document provides practical examples of using the new `get_ha_entity_history` function for analyzing heating systems, HVAC performance, and automation debugging.

## Basic Usage Examples

### 1. Analyze Thermostat Temperature Over Last 6 Hours

```python
# Get temperature history for the last 6 hours
history_data = await supervisor_api.get_ha_entity_history(
    entity_id="sensor.diyless_thermostat_1_ch_temperature",
    start_time="-6h",
    end_time="now",
    limit=500
)

print(f"Temperature changes: {history_data['total_changes']}")
print(f"Average temperature: {history_data['statistics']['value_statistics']['average']:.1f}°C")
print(f"Min/Max: {history_data['statistics']['value_statistics']['min']:.1f}°C / {history_data['statistics']['value_statistics']['max']:.1f}°C")
```

### 2. Monitor Heating System Efficiency (24 Hours)

```python
# Analyze CV temperature modulation patterns
cv_history = await supervisor_api.get_ha_entity_history(
    entity_id="sensor.cv_temperature",
    start_time="-24h",
    end_time="now",
    minimal_change=0.5  # Filter out noise < 0.5°C
)

# Analyze flame sensor activation
flame_history = await supervisor_api.get_ha_entity_history(
    entity_id="binary_sensor.flame_sensor",
    start_time="-24h",
    end_time="now"
)

print(f"CV temperature changes (>0.5°C): {cv_history['total_changes']}")
print(f"Flame sensor activations: {flame_history['total_changes']}")
print(f"Heating cycles per hour: {flame_history['statistics']['changes_per_hour']:.1f}")
```

### 3. Debug Automation Timing Issues

```python
# Check when thermostat setpoint was changed
setpoint_history = await supervisor_api.get_ha_entity_history(
    entity_id="climate.thermostat_setpoint",
    start_time="-12h",
    end_time="now"
)

# Check pump activation timing
pump_history = await supervisor_api.get_ha_entity_history(
    entity_id="switch.heating_pump",
    start_time="-12h", 
    end_time="now"
)

print("Thermostat setpoint changes:")
for change in setpoint_history['state_changes'][:5]:  # Show last 5 changes
    print(f"  {change['timestamp']}: {change['state']}°C")

print("Pump activation timeline:")
for change in pump_history['state_changes'][:10]:  # Show last 10 changes
    print(f"  {change['timestamp']}: {change['state']}")
```

### 4. Weekly Performance Analysis

```python
# Get week-long temperature data for pattern analysis
weekly_temp = await supervisor_api.get_ha_entity_history(
    entity_id="sensor.living_room_temperature",
    start_time="-7d",
    end_time="now",
    limit=2000,
    minimal_change=0.1
)

# Extract daily patterns
daily_stats = {}
for change in weekly_temp['state_changes']:
    timestamp = datetime.fromisoformat(change['timestamp'].replace('Z', '+00:00'))
    day = timestamp.strftime('%A')
    hour = timestamp.hour
    
    if day not in daily_stats:
        daily_stats[day] = {'temps': [], 'changes': 0}
    
    if 'numeric_value' in change:
        daily_stats[day]['temps'].append(change['numeric_value'])
    daily_stats[day]['changes'] += 1

# Print daily averages
for day, stats in daily_stats.items():
    if stats['temps']:
        avg_temp = sum(stats['temps']) / len(stats['temps'])
        print(f"{day}: {avg_temp:.1f}°C average, {stats['changes']} changes")
```

## Advanced Use Cases

### 5. Identify System Inefficiencies

```python
# Compare outdoor temperature vs heating demand
outdoor_temp = await supervisor_api.get_ha_entity_history(
    entity_id="sensor.outdoor_temperature",
    start_time="-24h",
    end_time="now",
    minimal_change=0.5
)

heating_demand = await supervisor_api.get_ha_entity_history(
    entity_id="sensor.heating_demand_percentage",
    start_time="-24h", 
    end_time="now",
    minimal_change=1.0
)

# Analyze correlation
print("System Efficiency Analysis:")
print(f"Outdoor temp range: {outdoor_temp['statistics']['value_statistics']['min']:.1f}°C to {outdoor_temp['statistics']['value_statistics']['max']:.1f}°C")
print(f"Average heating demand: {heating_demand['statistics']['value_statistics']['average']:.1f}%")
print(f"Heating system utilization: {heating_demand['statistics']['changes_per_hour']:.1f} adjustments/hour")
```

### 6. Predictive Maintenance

```python
# Monitor system switching frequency
high_frequency_entities = [
    "binary_sensor.flame_sensor",
    "switch.heating_pump", 
    "binary_sensor.dhw_demand"
]

maintenance_alerts = []

for entity in high_frequency_entities:
    history = await supervisor_api.get_ha_entity_history(
        entity_id=entity,
        start_time="-24h",
        end_time="now"
    )
    
    changes_per_hour = history['statistics']['changes_per_hour']
    
    # Set thresholds for different components
    if "flame" in entity and changes_per_hour > 10:
        maintenance_alerts.append(f"High flame sensor activity: {changes_per_hour:.1f} cycles/hour")
    elif "pump" in entity and changes_per_hour > 8:
        maintenance_alerts.append(f"Frequent pump cycling: {changes_per_hour:.1f} cycles/hour")

if maintenance_alerts:
    print("Maintenance Alerts:")
    for alert in maintenance_alerts:
        print(f"  ⚠️  {alert}")
```

### 7. Energy Usage Correlation

```python
# Analyze relationship between temperature and energy usage
temperature_history = await supervisor_api.get_ha_entity_history(
    entity_id="sensor.living_room_temperature",
    start_time="-7d",
    end_time="now",
    minimal_change=0.2
)

energy_history = await supervisor_api.get_ha_entity_history(
    entity_id="sensor.energy_consumption_daily",
    start_time="-7d",
    end_time="now"
)

print("Energy Efficiency Analysis:")
print(f"Temperature stability: {temperature_history['statistics']['value_statistics']['total_variation']:.1f}°C range")
print(f"Daily energy changes: {energy_history['total_changes']}")

# Calculate rough efficiency metric
if temperature_history['statistics']['changes_per_hour'] > 0:
    efficiency_score = energy_history['statistics']['changes_per_hour'] / temperature_history['statistics']['changes_per_hour']
    print(f"System efficiency score: {efficiency_score:.2f}")
```

## Time Format Examples

The function supports various time formats:

```python
# Relative time formats
"-6h"    # 6 hours ago
"-24h"   # 24 hours ago  
"-7d"    # 7 days ago
"-2w"    # 2 weeks ago

# ISO 8601 formats
"2024-01-06T10:00:00Z"         # UTC time
"2024-01-06T10:00:00+01:00"    # With timezone
"2024-01-06T10:00:00"          # Local time

# Special values
"now"    # Current time (default for end_time)
None     # Use defaults (12 hours ago for start_time, now for end_time)
```

## Response Format

The function returns a comprehensive dictionary:

```json
{
    "entity_id": "sensor.temperature",
    "query_period": {
        "start": "2024-01-06T04:00:00Z",
        "end": "2024-01-06T10:00:00Z", 
        "duration_hours": 6.0
    },
    "total_changes": 45,
    "state_changes": [
        {
            "timestamp": "2024-01-06T04:15:23Z",
            "state": "21.5",
            "numeric_value": 21.5,
            "unit": "°C",
            "friendly_name": "Living Room Temperature"
        }
    ],
    "statistics": {
        "type": "numeric",
        "total_changes": 45,
        "numeric_changes": 45,
        "time_period_hours": 6.0,
        "changes_per_hour": 7.5,
        "value_statistics": {
            "min": 20.8,
            "max": 22.1, 
            "average": 21.4,
            "first_value": 21.0,
            "last_value": 21.5,
            "total_variation": 1.3
        },
        "unit": "°C"
    }
}
```

This historical data enables comprehensive analysis of home automation systems, making it possible to optimize energy usage, predict maintenance needs, and debug complex automation scenarios.