#!/usr/bin/env python3
"""
Test script for the get_ha_entity_history function.
This script tests the new historical entity data retrieval functionality.
"""

import json
import asyncio
import sys
import os
from datetime import datetime, timedelta

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from supervisor_api import SupervisorAPI

async def test_entity_history():
    """Test the get_ha_entity_history function."""
    print("Testing Home Assistant Entity History Retrieval")
    print("=" * 50)
    
    # Test entity ID - replace with an actual entity from your Home Assistant
    test_entity = "sensor.diyless_thermostat_1_ch_temperature"
    
    try:
        supervisor_api = SupervisorAPI()
        print(f"Testing entity: {test_entity}")
        
        # Test 1: Basic history retrieval (last 6 hours)
        print("\n1. Testing basic history retrieval (last 6 hours)...")
        history_data = await supervisor_api.get_ha_entity_history(
            entity_id=test_entity,
            start_time="-6h",
            end_time="now",
            limit=100
        )
        
        print(f"   - Retrieved {history_data.get('total_changes', 0)} state changes")
        if history_data.get('statistics'):
            stats = history_data['statistics']
            if stats.get('type') == 'numeric':
                value_stats = stats.get('value_statistics', {})
                print(f"   - Min: {value_stats.get('min')}, Max: {value_stats.get('max')}")
                print(f"   - Average: {value_stats.get('average', 0):.2f}")
                print(f"   - Changes per hour: {stats.get('changes_per_hour', 0):.2f}")
        
        # Test 2: History with minimal change filter
        print("\n2. Testing history with minimal change filter (0.1)...")
        filtered_history = await supervisor_api.get_ha_entity_history(
            entity_id=test_entity,
            start_time="-12h",
            end_time="now",
            limit=200,
            minimal_change=0.1
        )
        
        print(f"   - Retrieved {filtered_history.get('total_changes', 0)} significant changes")
        
        # Test 3: Extended history (24 hours)
        print("\n3. Testing extended history (last 24 hours)...")
        extended_history = await supervisor_api.get_ha_entity_history(
            entity_id=test_entity,
            start_time="-24h",
            end_time="now",
            limit=500
        )
        
        print(f"   - Retrieved {extended_history.get('total_changes', 0)} state changes over 24h")
        
        # Test 4: Test with non-existent entity
        print("\n4. Testing with non-existent entity...")
        nonexistent_history = await supervisor_api.get_ha_entity_history(
            entity_id="sensor.nonexistent_entity",
            start_time="-1h",
            end_time="now"
        )
        
        if nonexistent_history.get('error'):
            print(f"   - Correctly handled non-existent entity: {nonexistent_history['error']}")
        else:
            print(f"   - Retrieved {nonexistent_history.get('total_changes', 0)} changes (might be empty)")
        
        print("\n" + "=" * 50)
        print("Test completed successfully!")
        
        # Save a sample of the results for inspection
        with open('test_history_output.json', 'w') as f:
            json.dump({
                'basic_history': history_data,
                'filtered_history': filtered_history,
                'extended_history': extended_history,
                'nonexistent_history': nonexistent_history
            }, f, indent=2)
        
        print("Sample results saved to: test_history_output.json")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()

async def test_time_parsing():
    """Test the time parsing functionality."""
    print("\nTesting Time Parsing")
    print("=" * 30)
    
    supervisor_api = SupervisorAPI()
    
    test_cases = [
        ("-6h", "now"),
        ("-24h", "now"),
        ("-7d", "now"),
        (None, None),  # Should use defaults
        ("2024-01-01T00:00:00", "2024-01-01T12:00:00"),
    ]
    
    for start, end in test_cases:
        try:
            start_dt, end_dt = supervisor_api._parse_time_parameters(start, end)
            print(f"   - '{start}' to '{end}' -> {start_dt} to {end_dt}")
        except Exception as e:
            print(f"   - '{start}' to '{end}' -> ERROR: {e}")

if __name__ == "__main__":
    print("Home Assistant MCP Server - Entity History Test")
    print("Make sure you have MCP_ENABLE_HA_CLI=true and SUPERVISOR_TOKEN set")
    print()
    
    # Run the tests
    asyncio.run(test_time_parsing())
    asyncio.run(test_entity_history())