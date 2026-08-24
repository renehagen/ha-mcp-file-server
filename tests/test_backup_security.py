import asyncio
from dataclasses import replace
from io import BytesIO
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))
os.environ.setdefault("SUPERVISOR_TOKEN", "test-supervisor-token")

from backup_inspector import (  # noqa: E402
    BackupLimitError,
    BackupLimits,
    BackupValidationError,
    normalize_patterns,
    redact_sensitive_text,
    scan_backup_archive,
    scan_backup_archive_isolated,
    validate_backup_slug,
)
import mcp_server  # noqa: E402
from supervisor_api import SupervisorAPI  # noqa: E402


def tar_bytes(members):
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, content in members:
            payload = content if isinstance(content, bytes) else content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, BytesIO(payload))
    return output.getvalue()


class BackupScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.archive = Path(self.temp_dir.name) / "backup.tar"

    def write_archive(self, members):
        self.archive.write_bytes(tar_bytes(members))

    def test_location_only_results_contain_no_snippet_or_content(self):
        self.write_archive([("configuration.yaml", "password: extremely-sensitive\nentity_id: light.kitchen")])
        result = scan_backup_archive(
            self.archive, ["password"], BackupLimits(), include_content=False
        )
        self.assertEqual(result["matches"], [{"path": "backup.tar!configuration.yaml", "line": 1}])
        serialized = repr(result["matches"])
        self.assertNotIn("extremely-sensitive", serialized)
        self.assertNotIn("snippet", serialized)

    def test_explicit_content_is_redacted_including_context(self):
        self.write_archive([(
            "configuration.yaml",
            "api_key: abcdefghijklmnopqrstuvwxyz with trailing words\n"
            "match: yes\nAuthorization: Bearer abcdefghijklmnop\n"
            "AKIA" "ABCDEFGHIJKLMNOP\n"
            "MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDemo",
        )])
        result = scan_backup_archive(
            self.archive,
            ["match"],
            BackupLimits(),
            include_content=True,
            context_lines=1,
        )
        snippet = result["matches"][0]["snippet"]
        self.assertIn("[REDACTED]", snippet)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", snippet)
        self.assertNotIn("trailing words", snippet)
        self.assertNotIn("abcdefghijklmnop", snippet)

    def test_prefixed_keys_and_complete_private_keys_are_redacted(self):
        private_material = (
            "-----BEGIN " "ENCRYPTED PRIVATE KEY-----\n"
            "SHORTSECRETBODY1234567890\n"
            "-----END " "ENCRYPTED PRIVATE KEY-----"
        )
        value = (
            "SUPERVISOR_TOKEN=supervisor-secret\n"
            "mqtt_password: password-with-spaces and more\n"
            f"{private_material}\n"
            "credential: QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo5ODc2NTQzMjE="
        )
        redacted = redact_sensitive_text(value)
        for secret in (
            "supervisor-secret",
            "password-with-spaces",
            "SHORTSECRETBODY1234567890",
            "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo5ODc2NTQzMjE=",
        ):
            self.assertNotIn(secret, redacted)
        self.assertIn("[REDACTED_PRIVATE_KEY_BLOCK]", redacted)

    def test_nested_archive_is_scanned_without_extracting_paths(self):
        inner = tar_bytes([("config/automations.yaml", "alias: Heat\nentity_id: climate.office")])
        self.write_archive([("homeassistant.tar", inner)])
        result = scan_backup_archive(self.archive, ["climate.office"], BackupLimits())
        self.assertEqual(result["matches"][0]["line"], 2)
        self.assertIn("homeassistant.tar!config/automations.yaml", result["matches"][0]["path"])
        self.assertEqual(result["stats"]["archives_scanned"], 2)

    def test_unsafe_member_paths_and_corrupt_archives_are_structured_errors(self):
        self.write_archive([("../../outside.yaml", "token: should-never-return")])
        unsafe = scan_backup_archive(self.archive, ["token"], BackupLimits(), include_content=True)
        self.assertEqual(unsafe["matches"], [])
        self.assertEqual(unsafe["stats"]["unsafe_members_skipped"], 1)
        self.assertTrue(unsafe["errors"])

        self.archive.write_bytes(b"not a tar archive")
        corrupt = scan_backup_archive(self.archive, ["anything"], BackupLimits())
        self.assertEqual(corrupt["matches"], [])
        self.assertTrue(corrupt["errors"])

    def test_member_unpacked_match_and_time_limits_stop_scans(self):
        self.write_archive([("one.yaml", "match: one"), ("two.yaml", "match: two")])
        member_limited = scan_backup_archive(
            self.archive, ["match"], replace(BackupLimits(), max_archive_members=1)
        )
        self.assertTrue(member_limited["truncated"])
        self.assertIn("archive-member limit", member_limited["errors"][-1]["error"])

        unpack_limited = scan_backup_archive(
            self.archive, ["match"], replace(BackupLimits(), max_unpacked_bytes=5)
        )
        self.assertTrue(unpack_limited["truncated"])
        self.assertIn("unpacked-byte limit", unpack_limited["errors"][-1]["error"])

        match_limited = scan_backup_archive(
            self.archive, ["match"], BackupLimits(), max_matches=1
        )
        self.assertEqual(len(match_limited["matches"]), 1)
        self.assertTrue(match_limited["truncated"])

        with patch("backup_inspector.time.monotonic", side_effect=[0.0, 2.0]):
            time_limited = scan_backup_archive(
                self.archive, ["match"], replace(BackupLimits(), max_seconds=1.0)
            )
        self.assertTrue(time_limited["truncated"])
        self.assertIn("time limit", time_limited["errors"][-1]["error"])

    def test_slug_pattern_and_context_validation(self):
        self.assertEqual(validate_backup_slug("backup_2026-08-24"), "backup_2026-08-24")
        for invalid in ("", "../backup", "has space", "a" * 65, "x/y"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(BackupValidationError):
                    validate_backup_slug(invalid)

        with self.assertRaises(BackupLimitError):
            normalize_patterns(["x"] * 17, BackupLimits())
        with self.assertRaises(BackupLimitError):
            normalize_patterns(["x" * 129], BackupLimits())
        with self.assertRaises(BackupLimitError):
            scan_backup_archive(self.archive, ["match"], BackupLimits(), context_lines=4)

    def test_isolated_worker_enforces_a_hard_wall_clock_limit(self):
        self.write_archive([("configuration.yaml", "match: yes")])
        with self.assertRaises(BackupLimitError):
            scan_backup_archive_isolated(
                self.archive,
                ["match"],
                replace(BackupLimits(), max_seconds=0.000001),
            )


class BackupAccessAndDispatchTests(unittest.TestCase):
    def secure_runtime(self):
        return patch.multiple(
            mcp_server,
            ENABLE_HA_CLI=True,
            ENABLE_BACKUP_INSPECTION=True,
            BACKUP_ALLOW_CONTENT=True,
            API_KEY="a-strong-test-api-key-1234567890",
        )

    def test_backup_feature_requires_opt_in_and_strong_auth(self):
        with patch.multiple(
            mcp_server, ENABLE_HA_CLI=True, ENABLE_BACKUP_INSPECTION=False, API_KEY="x" * 30
        ):
            with self.assertRaises(PermissionError):
                mcp_server.require_backup_access()
        with patch.multiple(
            mcp_server, ENABLE_HA_CLI=True, ENABLE_BACKUP_INSPECTION=True, API_KEY="too-short"
        ):
            with self.assertRaises(PermissionError):
                mcp_server.require_backup_access()
        with patch.multiple(
            mcp_server, ENABLE_HA_CLI=True, ENABLE_BACKUP_INSPECTION=True, API_KEY="x" * 30
        ):
            with self.assertRaises(PermissionError):
                mcp_server.require_backup_access()
        with self.secure_runtime():
            mcp_server.require_backup_access()

    def test_content_requires_config_and_per_request_acknowledgement(self):
        with patch.multiple(
            mcp_server,
            ENABLE_HA_CLI=True,
            ENABLE_BACKUP_INSPECTION=True,
            BACKUP_ALLOW_CONTENT=False,
            API_KEY="varied-test-api-key-123456789",
        ):
            with self.assertRaises(PermissionError):
                mcp_server.require_backup_access(
                    include_content=True, acknowledge_sensitive_content=True
                )
        with self.secure_runtime():
            with self.assertRaises(PermissionError):
                mcp_server.require_backup_access(include_content=True)
            mcp_server.require_backup_access(
                include_content=True, acknowledge_sensitive_content=True
            )

    def test_content_flags_reject_non_boolean_json_values(self):
        invalid_pairs = [
            ("false", "false"),
            (1, True),
            (True, "true"),
            (None, False),
        ]
        with self.secure_runtime():
            for include_content, acknowledgement in invalid_pairs:
                with self.subTest(
                    include_content=include_content,
                    acknowledgement=acknowledgement,
                ):
                    with self.assertRaises(BackupValidationError):
                        mcp_server.require_backup_access(
                            include_content=include_content,
                            acknowledge_sensitive_content=acknowledgement,
                        )

    def test_search_rejects_string_false_before_contacting_supervisor(self):
        supervisor = AsyncMock()
        with self.secure_runtime(), patch.object(
            mcp_server, "SupervisorAPI", supervisor
        ), patch.object(
            mcp_server, "_BACKUP_SEARCH_SEMAPHORE", asyncio.Semaphore(1)
        ):
            with self.assertRaises(BackupValidationError):
                asyncio.run(mcp_server.search_ha_backups(
                    "match",
                    include_content="false",
                    acknowledge_sensitive_content="false",
                ))
        supervisor.assert_not_called()

    def test_tools_are_hidden_until_securely_configured(self):
        request = mcp_server.JsonRpcRequest(id=1, method="tools/list")
        with patch.multiple(
            mcp_server, ENABLE_HA_CLI=True, ENABLE_BACKUP_INSPECTION=False, API_KEY="x" * 30
        ):
            disabled = asyncio.run(mcp_server.handle_mcp_request(request))
        disabled_names = {tool["name"] for tool in disabled.result["tools"]}
        self.assertNotIn("search_ha_backups", disabled_names)

        with self.secure_runtime():
            enabled = asyncio.run(mcp_server.handle_mcp_request(request))
        enabled_names = {tool["name"] for tool in enabled.result["tools"]}
        self.assertIn("list_ha_backups", enabled_names)
        self.assertIn("search_ha_backups", enabled_names)

    def test_http_endpoint_requires_header_key_before_parsing(self):
        class FakeRequest:
            def __init__(self):
                self.parsed = False

            async def json(self):
                self.parsed = True
                return {"jsonrpc": "2.0", "id": 1, "method": "initialize"}

        with self.secure_runtime():
            missing = FakeRequest()
            with self.assertRaises(mcp_server.HTTPException):
                asyncio.run(mcp_server.mcp_post_endpoint(missing, x_mcp_api_key=None))
            self.assertFalse(missing.parsed)

            wrong = FakeRequest()
            with self.assertRaises(mcp_server.HTTPException):
                asyncio.run(mcp_server.mcp_post_endpoint(
                    wrong, x_mcp_api_key="wrong-key"
                ))
            self.assertFalse(wrong.parsed)

            accepted = FakeRequest()
            response = asyncio.run(mcp_server.mcp_post_endpoint(
                accepted, x_mcp_api_key="a-strong-test-api-key-1234567890"
            ))
            self.assertTrue(accepted.parsed)
            self.assertEqual(response["result"]["serverInfo"]["version"], mcp_server.VERSION)

    def test_query_string_key_is_rejected_and_header_is_accepted(self):
        class FakeRequest:
            def __init__(self, query_params):
                self.query_params = query_params

        next_handler = AsyncMock(return_value="accepted")
        rejected = asyncio.run(mcp_server.reject_query_string_credentials(
            FakeRequest({"code": "must-not-enter-a-url"}), next_handler
        ))
        accepted = asyncio.run(mcp_server.reject_query_string_credentials(
            FakeRequest({}), next_handler
        ))
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(accepted, "accepted")
        schema = mcp_server.app.openapi()
        parameters = schema["paths"]["/api/mcp"]["get"]["parameters"]
        self.assertEqual(
            [(item["name"], item["in"]) for item in parameters],
            [("X-MCP-API-Key", "header")],
        )

    def test_cli_parser_rejects_prefix_and_shell_injection(self):
        accepted = [
            "ha addons",
            "ha addons logs core_matter_server",
            "ha supervisor logs",
            "ha core logs",
            "ha host logs",
        ]
        for command in accepted:
            with self.subTest(command=command):
                self.assertEqual(mcp_server.parse_ha_cli_argv(command)[0], "ha")

        rejected = [
            "ha core logs; touch /tmp/pwned",
            "ha addonsXYZ",
            "ha addons logs good extra",
            "ha core logs $(id)",
            "ha core restart",
            "ha --help",
        ]
        for command in rejected:
            with self.subTest(command=command):
                with self.assertRaises((PermissionError, BackupValidationError)):
                    mcp_server.parse_ha_cli_argv(command)

    def test_backup_cli_forms_share_the_backup_gate(self):
        with patch.multiple(
            mcp_server, ENABLE_HA_CLI=True, ENABLE_BACKUP_INSPECTION=False, API_KEY="x" * 30
        ):
            with self.assertRaises(PermissionError):
                mcp_server.parse_ha_cli_argv("ha backups list")
        with self.secure_runtime():
            self.assertEqual(
                mcp_server.parse_ha_cli_argv("ha backups info valid_slug"),
                ["ha", "backups", "info", "valid_slug"],
            )

    def test_backup_cli_output_is_bounded_and_sanitized(self):
        class FakeSupervisor:
            async def list_backups(self):
                return {"data": {"backups": [{
                    "slug": "safe_slug",
                    "date": "2026-08-24",
                    "content": {"folders": ["config"]},
                    "SUPERVISOR_TOKEN": "must-not-leak",
                }]}}

        with self.secure_runtime(), patch.object(
            mcp_server, "SupervisorAPI", return_value=FakeSupervisor()
        ):
            listing = asyncio.run(
                mcp_server.execute_ha_cli_command("ha backups list")
            )
            info = asyncio.run(
                mcp_server.execute_ha_cli_command("ha backups info safe_slug")
            )
        for result in (listing, info):
            self.assertTrue(result["success"])
            self.assertNotIn("must-not-leak", result["stdout"])
            self.assertNotIn("folders", result["stdout"])
            self.assertNotIn("content", result["stdout"])

    def test_local_cli_fallback_uses_argv_not_a_shell(self):
        process = AsyncMock()
        process.communicate.return_value = (b"ok", b"")
        process.returncode = 0
        with patch.dict(os.environ, {}, clear=True), patch.object(
            mcp_server.asyncio, "create_subprocess_exec", AsyncMock(return_value=process)
        ) as create_exec, patch.multiple(mcp_server, ENABLE_HA_CLI=True):
            result = asyncio.run(mcp_server.execute_ha_cli_command("ha core logs"))
        create_exec.assert_awaited_once()
        self.assertEqual(create_exec.await_args.args[:3], ("ha", "core", "logs"))
        self.assertTrue(result["success"])


class BackupSearchIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.archive_bytes = tar_bytes([(
            "configuration.yaml",
            "password: top-secret-value\nentity_id: climate.office\n",
        )])

    def secure_runtime(self):
        return patch.multiple(
            mcp_server,
            ENABLE_HA_CLI=True,
            ENABLE_BACKUP_INSPECTION=True,
            BACKUP_ALLOW_CONTENT=True,
            API_KEY="a-strong-test-api-key-1234567890",
        )

    def test_search_uses_worker_cleans_temp_file_and_hides_content_by_default(self):
        destinations = []
        archive_bytes = self.archive_bytes

        class FakeSupervisor:
            async def list_backups(self):
                return {"data": {"backups": [{"slug": "backup_one", "date": "2026-08-24"}]}}

            async def download_backup(self, slug, destination, **kwargs):
                destinations.append(Path(destination))
                Path(destination).write_bytes(archive_bytes)
                return {"bytes": len(archive_bytes)}

        real_to_thread = asyncio.to_thread
        to_thread = AsyncMock(side_effect=real_to_thread)
        with self.secure_runtime(), patch.object(
            mcp_server, "SupervisorAPI", return_value=FakeSupervisor()
        ), patch.object(mcp_server.asyncio, "to_thread", to_thread):
            result = asyncio.run(mcp_server.search_ha_backups("entity_id"))

        self.assertEqual(result["total_matches"], 1)
        self.assertNotIn("snippet", result["results"][0]["matches"][0])
        self.assertNotIn("top-secret-value", repr(result))
        self.assertTrue(destinations)
        self.assertFalse(destinations[0].exists())
        to_thread.assert_awaited_once()

    def test_enabled_content_is_redacted_and_protected_failure_is_safe(self):
        archive_bytes = self.archive_bytes

        class FakeSupervisor:
            async def list_backups(self):
                return {"data": {"backups": [
                    {"slug": "normal", "date": "2026-08-24"},
                    {"slug": "protected", "date": "2026-08-23", "protected": True},
                ]}}

            async def download_backup(self, slug, destination, **kwargs):
                if slug == "protected":
                    raise RuntimeError("protected backup cannot be decrypted; token: should-hide")
                Path(destination).write_bytes(archive_bytes)
                return {"bytes": len(archive_bytes)}

        with self.secure_runtime(), patch.object(
            mcp_server, "SupervisorAPI", return_value=FakeSupervisor()
        ):
            result = asyncio.run(mcp_server.search_ha_backups(
                "password",
                max_backups=2,
                include_content=True,
                acknowledge_sensitive_content=True,
            ))

        serialized = repr(result)
        self.assertIn("[REDACTED]", serialized)
        self.assertNotIn("top-secret-value", serialized)
        self.assertNotIn("should-hide", serialized)
        self.assertTrue(result["errors"])

    def test_unknown_slug_and_single_concurrency_slot(self):
        class FakeSupervisor:
            async def list_backups(self):
                return {"data": {"backups": []}}

        with self.secure_runtime(), patch.object(
            mcp_server, "SupervisorAPI", return_value=FakeSupervisor()
        ):
            missing = asyncio.run(mcp_server.search_ha_backups(
                "x", backup_slugs=["missing_slug"]
            ))
        self.assertEqual(missing["missing_backup_slugs"], ["missing_slug"])
        self.assertEqual(missing["limits"]["max_concurrency"], 1)

    def test_busy_concurrency_slot_is_rejected(self):
        async def scenario():
            semaphore = asyncio.Semaphore(1)
            await semaphore.acquire()
            try:
                with self.secure_runtime(), patch.object(
                    mcp_server, "_BACKUP_SEARCH_SEMAPHORE", semaphore
                ):
                    with self.assertRaises(BackupLimitError):
                        await mcp_server.search_ha_backups("x")
            finally:
                semaphore.release()

        asyncio.run(scenario())

    def test_hard_deadline_includes_supervisor_listing(self):
        class HangingSupervisor:
            async def list_backups(self):
                await asyncio.Event().wait()

        limits = replace(mcp_server.BACKUP_LIMITS, max_seconds=0.01)
        with self.secure_runtime(), patch.object(
            mcp_server, "SupervisorAPI", return_value=HangingSupervisor()
        ), patch.object(
            mcp_server, "BACKUP_LIMITS", limits
        ), patch.object(
            mcp_server, "_BACKUP_SEARCH_SEMAPHORE", asyncio.Semaphore(1)
        ):
            with self.assertRaises(BackupLimitError):
                asyncio.run(mcp_server.search_ha_backups("x"))

    def test_temp_file_is_removed_when_worker_fails(self):
        destinations = []
        archive_bytes = self.archive_bytes

        class FakeSupervisor:
            async def list_backups(self):
                return {"data": {"backups": [{"slug": "backup_one"}]}}

            async def download_backup(self, slug, destination, **kwargs):
                destinations.append(Path(destination))
                Path(destination).write_bytes(archive_bytes)
                return {"bytes": len(archive_bytes)}

        with self.secure_runtime(), patch.object(
            mcp_server, "SupervisorAPI", return_value=FakeSupervisor()
        ), patch.object(
            mcp_server.asyncio, "to_thread", AsyncMock(side_effect=RuntimeError("worker failed"))
        ):
            result = asyncio.run(mcp_server.search_ha_backups("x"))
        self.assertTrue(result["errors"])
        self.assertFalse(destinations[0].exists())


class SupervisorDownloadTests(unittest.TestCase):
    class FakeContent:
        def __init__(self, chunks):
            self.chunks = chunks

        async def iter_chunked(self, size):
            for chunk in self.chunks:
                yield chunk

    class FakeResponse:
        def __init__(self, chunks, status=200):
            self.status = status
            self.content = SupervisorDownloadTests.FakeContent(chunks)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeSession:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def get(self, *args, **kwargs):
            return self.response

    def test_download_byte_limit_removes_partial_file(self):
        api = SupervisorAPI()
        response = self.FakeResponse([b"1234", b"5678"])
        session = self.FakeSession(response)
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "backup.tar"
            with patch("supervisor_api.aiohttp.ClientSession", return_value=session):
                with self.assertRaises(BackupLimitError):
                    asyncio.run(api.download_backup(
                        "valid_slug", str(destination), max_bytes=6, timeout_seconds=5
                    ))
            self.assertFalse(destination.exists())

    def test_download_success_and_slug_validation(self):
        api = SupervisorAPI()
        response = self.FakeResponse([b"1234"])
        session = self.FakeSession(response)
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "backup.tar"
            with patch("supervisor_api.aiohttp.ClientSession", return_value=session):
                result = asyncio.run(api.download_backup(
                    "valid_slug", str(destination), max_bytes=6, timeout_seconds=5
                ))
            self.assertEqual(result["bytes"], 4)
            self.assertEqual(destination.read_bytes(), b"1234")
            with self.assertRaises(BackupValidationError):
                asyncio.run(api.download_backup(
                    "../bad", str(destination), max_bytes=6, timeout_seconds=5
                ))

    def test_backup_list_falls_back_to_legacy_supervisor_endpoint(self):
        api = SupervisorAPI()
        api.call_supervisor_api = AsyncMock(side_effect=[
            RuntimeError("new endpoint unavailable"),
            {"data": {"snapshots": []}},
        ])
        result = asyncio.run(api.list_backups())
        self.assertEqual(result, {"data": {"snapshots": []}})
        self.assertEqual(
            [call.args[1] for call in api.call_supervisor_api.await_args_list],
            ["/backups", "/snapshots"],
        )


class ManifestSecurityTests(unittest.TestCase):
    def test_backup_is_not_mounted_or_generally_allowlisted(self):
        config = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("enable_backup_inspection: false", config)
        self.assertNotIn('- "/backup"', config)
        self.assertNotIn("- backup:", config)


if __name__ == "__main__":
    unittest.main()
