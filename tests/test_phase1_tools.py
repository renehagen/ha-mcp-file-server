import asyncio
import os
import shutil
import sys
import tempfile
import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))
os.environ.setdefault("SUPERVISOR_TOKEN", "test-token")


def install_missing_dependency_stubs():
    """Let focused unit tests run without the full add-on runtime dependencies installed."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        fastapi_stub = types.ModuleType("fastapi")

        class FastAPI:
            def __init__(self, *args, **kwargs):
                pass

            def get(self, *args, **kwargs):
                return lambda func: func

            def post(self, *args, **kwargs):
                return lambda func: func

            def middleware(self, *args, **kwargs):
                return lambda func: func

        class HTTPException(Exception):
            def __init__(self, status_code=None, detail=None):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail

        fastapi_stub.FastAPI = FastAPI
        fastapi_stub.HTTPException = HTTPException
        fastapi_stub.Request = object
        fastapi_stub.Query = lambda default=None: default
        sys.modules["fastapi"] = fastapi_stub

    try:
        import aiohttp  # noqa: F401
    except ImportError:
        aiohttp_stub = types.ModuleType("aiohttp")
        aiohttp_stub.ClientResponse = object

        class ClientSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        aiohttp_stub.ClientSession = ClientSession
        sys.modules["aiohttp"] = aiohttp_stub

    try:
        import aiofiles  # noqa: F401
    except ImportError:
        aiofiles_stub = types.ModuleType("aiofiles")

        class AsyncFile:
            def __init__(self, path, mode="r", encoding=None):
                self.file = open(path, mode, encoding=encoding)

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                self.file.close()
                return False

            async def read(self):
                return self.file.read()

            async def write(self, content):
                return self.file.write(content)

            def __aiter__(self):
                return self

            async def __anext__(self):
                line = self.file.readline()
                if line:
                    return line
                raise StopAsyncIteration

        aiofiles_stub.open = lambda path, mode="r", encoding=None: AsyncFile(path, mode, encoding)
        sys.modules["aiofiles"] = aiofiles_stub

    try:
        import paho.mqtt.client  # noqa: F401
    except ImportError:
        paho_stub = types.ModuleType("paho")
        mqtt_package_stub = types.ModuleType("paho.mqtt")
        mqtt_client_stub = types.ModuleType("paho.mqtt.client")

        class CallbackAPIVersion:
            VERSION2 = 2

        class Client:
            def __init__(self, *args, **kwargs):
                pass

        mqtt_client_stub.CallbackAPIVersion = CallbackAPIVersion
        mqtt_client_stub.Client = Client
        sys.modules["paho"] = paho_stub
        sys.modules["paho.mqtt"] = mqtt_package_stub
        sys.modules["paho.mqtt.client"] = mqtt_client_stub


install_missing_dependency_stubs()

import mcp_server
from file_handler import FileHandler
from supervisor_api import SupervisorAPI
from yaml_validator import YAML, YAMLValidator


class ManualTempDirectory:
    def __init__(self, parent):
        self.path = Path(parent) / f"mcp-test-{uuid.uuid4().hex}"
        self.path.mkdir(parents=True, exist_ok=False)
        self.name = str(self.path)

    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)


def make_temp_directory():
    test_tmpdir = os.environ.get("MCP_TEST_TMPDIR")
    if test_tmpdir:
        Path(test_tmpdir).mkdir(parents=True, exist_ok=True)
        return ManualTempDirectory(test_tmpdir)
    return tempfile.TemporaryDirectory()


class FakeSupervisorAPI:
    async def call_service(self, domain, service, target=None, data=None, return_response=False):
        return {
            "success": True,
            "domain": domain,
            "service": service,
            "context_id": "ctx-123",
            "response": {"ok": True} if return_response else None,
            "error": None,
            "target": target,
            "data": data,
        }


class ServiceAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.old_enabled = mcp_server.ENABLE_HA_CLI
        self.old_read_only = mcp_server.READ_ONLY
        self.old_allowed = list(mcp_server.ALLOWED_SERVICES)
        mcp_server.ENABLE_HA_CLI = True
        mcp_server.READ_ONLY = False
        mcp_server.ALLOWED_SERVICES = ["number.set_value"]

    def tearDown(self):
        mcp_server.ENABLE_HA_CLI = self.old_enabled
        mcp_server.READ_ONLY = self.old_read_only
        mcp_server.ALLOWED_SERVICES = self.old_allowed

    def test_call_allowed_service_accepts_allowlisted_service(self):
        with patch.object(mcp_server, "SupervisorAPI", return_value=FakeSupervisorAPI()):
            result = asyncio.run(
                mcp_server.call_allowed_service(
                    "number",
                    "set_value",
                    target={"entity_id": "number.example"},
                    data={"value": 0},
                    return_response=True,
                )
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["context_id"], "ctx-123")
        self.assertEqual(result["response"], {"ok": True})

    def test_call_allowed_service_rejects_unlisted_service(self):
        with self.assertRaisesRegex(Exception, "not allowed"):
            asyncio.run(mcp_server.call_allowed_service("light", "turn_on"))

    def test_call_allowed_service_rejects_read_only_mode(self):
        mcp_server.READ_ONLY = True
        with self.assertRaisesRegex(Exception, "read-only"):
            asyncio.run(mcp_server.call_allowed_service("number", "set_value"))

    def test_call_allowed_service_rejects_disabled_ha_tools(self):
        mcp_server.ENABLE_HA_CLI = False
        with self.assertRaisesRegex(Exception, "disabled"):
            asyncio.run(mcp_server.call_allowed_service("number", "set_value"))

    def test_default_allowlist_includes_homeassistant_check_config(self):
        self.assertIn("homeassistant.check_config", mcp_server.DEFAULT_ALLOWED_SERVICES)


class ReloadWrapperTests(unittest.TestCase):
    def test_reload_automations_maps_automation_id_to_service_data(self):
        call_mock = AsyncMock(return_value={"success": True})
        with patch.object(mcp_server, "call_allowed_service", call_mock):
            request = mcp_server.JsonRpcRequest(
                id=1,
                method="tools/call",
                params={
                    "name": "reload_automations",
                    "arguments": {"automation_id": "safety_stop"},
                },
            )
            response = asyncio.run(mcp_server.handle_mcp_request(request))

        self.assertIsNone(response.error)
        call_mock.assert_awaited_once_with("automation", "reload", data={"id": "safety_stop"})

    def test_reload_integration_maps_entry_id(self):
        call_mock = AsyncMock(return_value={"success": True})
        with patch.object(mcp_server, "call_allowed_service", call_mock):
            request = mcp_server.JsonRpcRequest(
                id=1,
                method="tools/call",
                params={
                    "name": "reload_integration",
                    "arguments": {"entry_id": "entry-123"},
                },
            )
            response = asyncio.run(mcp_server.handle_mcp_request(request))

        self.assertIsNone(response.error)
        call_mock.assert_awaited_once_with(
            "homeassistant",
            "reload_config_entry",
            data={"entry_id": "entry-123"},
        )


class SupervisorAPICallServiceTests(unittest.TestCase):
    def test_call_service_returns_context_and_response(self):
        api = SupervisorAPI()
        api.call_ha_websocket = AsyncMock(return_value={
            "context": {"id": "ctx-abc"},
            "response": {"changed": True},
        })

        result = asyncio.run(
            api.call_service(
                "number",
                "set_value",
                target={"entity_id": "number.example"},
                data={"value": 0},
                return_response=True,
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["context_id"], "ctx-abc")
        self.assertEqual(result["response"], {"changed": True})
        api.call_ha_websocket.assert_awaited_once_with({
            "type": "call_service",
            "domain": "number",
            "service": "set_value",
            "target": {"entity_id": "number.example"},
            "service_data": {"value": 0},
            "return_response": True,
        })

    def test_call_service_propagates_websocket_error(self):
        api = SupervisorAPI()
        api.call_ha_websocket = AsyncMock(side_effect=Exception("HA denied"))

        with self.assertRaisesRegex(Exception, "HA denied"):
            asyncio.run(api.call_service("number", "set_value"))


@unittest.skipIf(YAML is None, "ruamel.yaml is not installed in this Python environment")
class YAMLValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_directory()
        self.base = Path(self.tmp.name)
        self.file_handler = FileHandler([str(self.base)])
        self.validator = YAMLValidator(self.file_handler)

    def tearDown(self):
        self.tmp.cleanup()

    def write_yaml(self, name, content):
        path = self.base / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_warns_for_ambiguous_plain_scalar(self):
        path = self.write_yaml("automation.yaml", "alias: test\ntrigger: []\naction:\n  - option: off\n")
        result = asyncio.run(self.validator.validate_yaml_file(path))

        self.assertTrue(result["valid"])
        self.assertEqual(result["warnings"][0]["type"], "ambiguous_plain_scalar")
        self.assertEqual(result["warnings"][0]["line"], 4)

    def test_reports_duplicate_key(self):
        path = self.write_yaml("duplicate.yaml", "alias: one\nalias: two\n")
        result = asyncio.run(self.validator.validate_yaml_file(path))

        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["type"], "duplicate_key")

    def test_validates_automation_structure(self):
        path = self.write_yaml("automation.yaml", "- alias: ok\n  trigger: []\n  action: []\n")
        result = asyncio.run(self.validator.validate_automation_file(path))

        self.assertTrue(result["valid"])
        self.assertEqual(result["automation_count"], 1)


class TraceTests(unittest.TestCase):
    def test_get_automation_trace_summary_uses_attribute_id_and_limits_runs(self):
        test_case = self

        class TraceSupervisor:
            async def get_state(self, entity_id):
                return {"state": {"attributes": {"id": "actual_automation_id"}}}

            async def list_traces(self, domain, item_id):
                test_case.assertEqual(domain, "automation")
                test_case.assertEqual(item_id, "actual_automation_id")
                return [
                    {"run_id": "run-1", "timestamp": "2026-06-30T10:00:00+00:00"},
                    {"run_id": "run-2", "timestamp": "2026-06-30T09:00:00+00:00"},
                ]

            async def get_trace(self, domain, item_id, run_id):
                return {
                    "trace": {"trigger": {"platform": "state"}},
                    "action/0": {
                        "result": {
                            "choice": "conditions/0",
                            "service": "number.set_value",
                            "service_data": {"value": 0},
                        }
                    },
                }

        old_enabled = mcp_server.ENABLE_HA_CLI
        mcp_server.ENABLE_HA_CLI = True
        try:
            with patch.object(mcp_server, "SupervisorAPI", return_value=TraceSupervisor()):
                result = asyncio.run(
                    mcp_server.get_automation_trace_summary(
                        "automation.zendure_safety_stop",
                        last_n=1,
                        include_raw=False,
                    )
                )
        finally:
            mcp_server.ENABLE_HA_CLI = old_enabled

        self.assertEqual(result["item_id"], "actual_automation_id")
        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["traces"][0]["trigger"], {"platform": "state"})
        self.assertEqual(result["traces"][0]["chosen_paths"][0]["choice"], "conditions/0")
        self.assertEqual(result["traces"][0]["service_calls"][0]["service"], "number.set_value")


class Batch2LogQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = make_temp_directory()
        self.base = Path(self.tmp.name)
        self.file_handler = FileHandler([str(self.base)])

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_relative_time_supports_minutes(self):
        before = datetime.now().astimezone() - timedelta(minutes=30)
        parsed = mcp_server._parse_relative_or_iso_time("-30m")
        after = datetime.now().astimezone() - timedelta(minutes=30)

        self.assertLessEqual(before, parsed)
        self.assertGreaterEqual(after, parsed)

    def test_query_logs_filters_tail_by_since_level_logger_and_text(self):
        log_path = self.base / "home-assistant.log"
        log_path.write_text(
            "\n".join([
                "2026-06-30 10:00:00.000 ERROR (MainThread) [homeassistant.components.automation.test] First error",
                "Traceback details are kept with the previous record",
                "2026-06-30 10:01:00 WARNING (MainThread) [custom_components.zendure] Battery warning",
                "2026-06-30 10:02:00 INFO (MainThread) [homeassistant.core] Started",
                "2026-06-30 10:03:00 ERROR (MainThread) [custom_components.zendure] Battery unavailable",
            ]),
            encoding="utf-8"
        )

        with patch.object(mcp_server, "file_handler", self.file_handler):
            result = asyncio.run(
                mcp_server.query_logs(
                    path=str(log_path),
                    since="2026-06-30T10:02:30",
                    level=["ERROR"],
                    logger_filter="zendure",
                    text_filter=["battery", "unavailable"],
                    match_mode="all",
                )
            )

        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["order"], "newest_first")
        self.assertEqual(result["lines"][0]["level"], "ERROR")
        self.assertEqual(result["lines"][0]["logger"], "custom_components.zendure")
        self.assertIn("Battery unavailable", result["lines"][0]["message"])


class Batch2StateSnapshotTests(unittest.TestCase):
    def test_get_states_filters_attributes_and_marks_missing_entities(self):
        api = SupervisorAPI()
        api.call_ha_api = AsyncMock(return_value=[
            {
                "entity_id": "sensor.temperature",
                "state": "21.5",
                "last_changed": "2026-06-30T10:00:00+00:00",
                "last_updated": "2026-06-30T10:01:00+00:00",
                "attributes": {
                    "friendly_name": "Temperature",
                    "unit_of_measurement": "C",
                    "ignored": True,
                },
            }
        ])

        result = asyncio.run(
            api.get_states(
                ["sensor.temperature", "sensor.missing"],
                attributes=["friendly_name", "unit_of_measurement"],
            )
        )

        api.call_ha_api.assert_awaited_once_with("GET", "/states")
        self.assertEqual(result["requested_count"], 2)
        self.assertEqual(result["missing"], ["sensor.missing"])
        self.assertEqual(result["states"][0]["state"], "21.5")
        self.assertEqual(
            result["states"][0]["attributes"],
            {"friendly_name": "Temperature", "unit_of_measurement": "C"},
        )
        self.assertFalse(result["states"][1]["found"])


class Batch2HistoryTests(unittest.TestCase):
    def test_supervisor_relative_time_supports_minutes(self):
        api = SupervisorAPI()
        reference = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)

        result = api._parse_relative_time("-90m", reference)

        self.assertEqual(result, reference - timedelta(minutes=90))

    def test_unavailable_transitions_only_keeps_edges(self):
        api = SupervisorAPI()
        raw_states = [
            {"state": "on", "last_changed": "2026-06-30T10:00:00+00:00", "attributes": {}},
            {
                "state": "unavailable",
                "last_changed": "2026-06-30T10:01:00+00:00",
                "attributes": {},
                "context": {"id": "ctx-unavailable"},
            },
            {
                "state": "off",
                "last_changed": "2026-06-30T10:02:00+00:00",
                "attributes": {},
                "context": {"id": "ctx-off", "parent_id": "ctx-unavailable"},
            },
            {"state": "on", "last_changed": "2026-06-30T10:03:00+00:00", "attributes": {}},
        ]

        result = api._process_state_changes(raw_states, unavailable_transitions_only=True)

        self.assertEqual([item["state"] for item in result], ["unavailable", "off"])
        self.assertEqual(result[0]["from_state"], "on")
        self.assertEqual(result[0]["context_id"], "ctx-unavailable")
        self.assertEqual(result[1]["from_state"], "unavailable")
        self.assertEqual(result[1]["parent_id"], "ctx-unavailable")

    def test_multi_entity_history_returns_stats_timeline_and_unavailable_periods(self):
        api = SupervisorAPI()
        api.call_ha_api = AsyncMock(return_value=[
            [
                {
                    "entity_id": "sensor.power",
                    "state": "0",
                    "last_changed": "2026-06-30T10:00:00+00:00",
                    "attributes": {"unit_of_measurement": "W"},
                },
                {
                    "entity_id": "sensor.power",
                    "state": "500",
                    "last_changed": "2026-06-30T10:10:00+00:00",
                    "attributes": {"unit_of_measurement": "W"},
                },
                {
                    "entity_id": "sensor.power",
                    "state": "1000",
                    "last_changed": "2026-06-30T10:20:00+00:00",
                    "attributes": {"unit_of_measurement": "W"},
                },
            ],
            [
                {
                    "entity_id": "sensor.zendure",
                    "state": "ok",
                    "last_changed": "2026-06-30T10:00:00+00:00",
                    "attributes": {},
                },
                {
                    "entity_id": "sensor.zendure",
                    "state": "unavailable",
                    "last_changed": "2026-06-30T10:05:00+00:00",
                    "attributes": {},
                },
                {
                    "entity_id": "sensor.zendure",
                    "state": "ok",
                    "last_changed": "2026-06-30T10:15:00+00:00",
                    "attributes": {},
                },
            ],
        ])

        result = asyncio.run(
            api.get_ha_entities_history(
                ["sensor.power", "sensor.zendure"],
                start_time="2026-06-30T10:00:00+00:00",
                end_time="2026-06-30T10:30:00+00:00",
                include_timeline=True,
            )
        )

        api.call_ha_api.assert_awaited_once()
        power = result["entities"][0]
        zendure = result["entities"][1]
        self.assertEqual(power["statistics"]["type"], "numeric")
        self.assertEqual(power["statistics"]["value_statistics"]["min"], 0)
        self.assertEqual(power["statistics"]["value_statistics"]["max"], 1000)
        self.assertEqual(power["statistics"]["value_statistics"]["average"], 500)
        self.assertEqual(zendure["availability"]["period_count"], 1)
        self.assertEqual(zendure["availability"]["total_unavailable_minutes"], 10)
        self.assertEqual(result["summary"]["total_returned_changes"], 6)
        self.assertEqual(result["timeline"][0]["entity_id"], "sensor.power")


class Batch2AddonManagementTests(unittest.TestCase):
    def test_runtime_status_reports_effective_flags(self):
        old_enabled = mcp_server.ENABLE_HA_CLI
        old_read_only = mcp_server.READ_ONLY
        try:
            mcp_server.ENABLE_HA_CLI = True
            mcp_server.READ_ONLY = False
            result = mcp_server.get_mcp_runtime_status()
        finally:
            mcp_server.ENABLE_HA_CLI = old_enabled
            mcp_server.READ_ONLY = old_read_only

        self.assertEqual(result["version"], mcp_server.VERSION)
        self.assertTrue(result["ha_cli_enabled"])
        self.assertFalse(result["read_only"])

    def test_get_mcp_addon_info_includes_info_stats_logs_and_runtime(self):
        class AddonSupervisor:
            async def get_addon_info(self, addon_slug):
                return {"slug": addon_slug, "state": "started", "options": {"enable_ha_cli": True}}

            async def get_addon_stats(self, addon_slug):
                return {"cpu_percent": 1.5}

            async def get_addon_logs(self, addon_slug):
                return "\n".join(["old", "new"])

        old_enabled = mcp_server.ENABLE_HA_CLI
        mcp_server.ENABLE_HA_CLI = True
        try:
            with patch.object(mcp_server, "SupervisorAPI", return_value=AddonSupervisor()):
                result = asyncio.run(
                    mcp_server.get_mcp_addon_info(
                        addon_slug="local_mcp_file_server",
                        include_logs=True,
                        log_lines=1,
                    )
                )
        finally:
            mcp_server.ENABLE_HA_CLI = old_enabled

        self.assertEqual(result["info"]["state"], "started")
        self.assertEqual(result["stats"]["cpu_percent"], 1.5)
        self.assertEqual(result["logs"]["text"], "new")
        self.assertTrue(result["runtime"]["ha_cli_enabled"])


if __name__ == "__main__":
    unittest.main()
