"""Regression checks for private Git archive and selectable diagnostic destination.

The production exporter and the pure target helpers are exercised without importing
Home Assistant into the standalone CI test environment.
"""
from __future__ import annotations

import ast
import base64
from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "weather_router"


def load_exporter() -> ModuleType:
    package = ModuleType("_wr_log_git_test")
    package.__path__ = []
    constants = ModuleType("_wr_log_git_test.const")
    constants.DEV_BUILD_VERSION = "0.10.145"
    constants.DEV_LOADER_REV = "0.10-loader-148"
    constants.LOG_GIT_REPOSITORY = "TheDaimos/weather-router-dev"
    constants.LOG_GIT_ROOT = ".weather-router/logs"
    fake_aiohttp = ModuleType("aiohttp")
    fake_aiohttp.ClientSession = object
    spec = importlib.util.spec_from_file_location(
        "_wr_log_git_test.log_git_export", ROOT / "log_git_export.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        package.__name__: package,
        constants.__name__: constants,
        fake_aiohttp.__name__: fake_aiohttp,
    }):
        spec.loader.exec_module(module)
    return module


exporter = load_exporter()


class FakeGitHubResponse:
    status = 201

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self):
        return {
            "commit": {"sha": "0123456789abcdef", "html_url": "https://github.com/example/commit"},
            "content": {"html_url": "https://github.com/example/file"},
        }


class FakeGitHubSession:
    def __init__(self):
        self.upload = None

    def put(self, url, *, headers, json):
        self.upload = {"url": url, "headers": headers, "json": json}
        return FakeGitHubResponse()


class ArchiveContractTests(unittest.IsolatedAsyncioTestCase):
    def snapshot(self):
        return {
            "schema": "weather_router.routing_diagnostic.v1",
            "meta": {"trace_id": "rt-test-001", "completed_at": "2026-10-09T15:30:00Z"},
            "request": {"capability": "weather.radar.precipitation"},
            "context": {"latitude": 52.52, "longitude": 13.405},
            "candidates": [],
            "decision": {"status": "ready"},
            "debug": {"token": "a-super-private-secret", "info": "keep"},
        }

    async def test_private_archive_contract_path_metadata_and_redaction(self):
        session = FakeGitHubSession()
        writer = exporter.WeatherRouterLogGitClient(
            session, "token-value-very-private",
            repository="TheDaimos/Project-Log-And-Export",
            root="exports/weather-router",
            require_private=True,
        )
        result = await writer.async_export(self.snapshot(), branch="main")
        self.assertTrue(result["path"].startswith(
            "exports/weather-router/2026-10/routing-test/"
            "2026-10-09T15-30-00Z__weather-router__0.10.145__routing-test__rt-test-001-"
        ))
        self.assertEqual(result["repository"], "TheDaimos/Project-Log-And-Export")
        saved = json.loads(base64.b64decode(session.upload["json"]["content"]))
        self.assertEqual(saved["exportSchema"], "daimos-project-log-export-v1")
        self.assertEqual(saved["application"]["id"], "weather-router")
        self.assertEqual(saved["application"]["name"], "WeatherRouter")
        self.assertEqual(saved["application"]["version"], "0.10.145")
        self.assertEqual(saved["export"]["type"], "routing-test")
        self.assertEqual(saved["application"]["loader"], "0.10-loader-148")
        self.assertIsNone(saved["application"]["instanceId"])
        self.assertEqual(saved["test"]["runId"], "rt-test-001")
        self.assertIsNone(saved["test"]["id"])
        self.assertIsNone(saved["test"]["caseId"])
        self.assertIsNone(saved["test"]["status"])
        self.assertIsNone(saved["test"]["attempt"])
        self.assertIsNone(saved["test"]["counts"])
        self.assertIsNone(saved["test"]["capabilityUiNumber"])
        self.assertEqual(saved["test"]["capabilityId"], "weather.radar.precipitation")
        self.assertEqual(saved["export"]["exportedAt"], saved["exported_at"])
        self.assertEqual(saved["source"]["repository"], "TheDaimos/weather-router-dev")
        self.assertEqual(saved["log"]["context"]["latitude"], 52.52)
        self.assertEqual(saved["log"]["debug"]["token"], "<redacted>")
        self.assertNotIn("a-super-private-secret", str(saved))
        self.assertNotIn("token-value-very-private", str(saved))

    async def test_explicit_test_metadata_preserves_identity_without_inventing_results(self):
        session = FakeGitHubSession()
        snapshot = self.snapshot()
        snapshot["test"] = {
            "id": "P6-030-TEST1",
            "runId": "rt-test-001",
            "attempt": 3,
            "planStep": "P6-030",
            "capabilityUiNumber": "051 / 4",
            "counts": {"assertionsExecuted": 17},
            "status": "PASS",
        }
        client = exporter.WeatherRouterLogGitClient(session, "token-for-archive")
        await client.async_export(snapshot, branch="main")
        stored = json.loads(base64.b64decode(session.upload["json"]["content"]))
        self.assertEqual(stored["test"]["id"], "P6-030-TEST1")
        self.assertEqual(stored["test"]["caseId"], "P6-030-TEST1")
        self.assertEqual(stored["test"]["runId"], "rt-test-001")
        self.assertEqual(stored["test"]["attempt"], 3)
        self.assertEqual(stored["test"]["planStep"], "P6-030")
        self.assertEqual(stored["test"]["capabilityUiNumber"], "051 / 4")
        self.assertEqual(stored["test"]["counts"]["assertionsExecuted"], 17)
        self.assertEqual(stored["test"]["status"], "PASS")

    async def test_repeated_exports_keep_run_id_but_create_distinct_export_ids(self):
        session = FakeGitHubSession()
        client = exporter.WeatherRouterLogGitClient(session, "token-for-archive")
        snapshot = self.snapshot()
        await client.async_export(snapshot, branch="main")
        first = json.loads(base64.b64decode(session.upload["json"]["content"]))
        await client.async_export(snapshot, branch="main")
        second = json.loads(base64.b64decode(session.upload["json"]["content"]))
        self.assertNotEqual(first["export"]["exportId"], second["export"]["exportId"])
        self.assertEqual(first["test"]["runId"], second["test"]["runId"])

    async def test_suspicious_untrusted_metadata_is_not_indexed(self):
        session = FakeGitHubSession()
        snapshot = self.snapshot()
        snapshot["test"] = {
            "id": "https://example.org/testing?token=supersecret",
            "runId": "Bearer secret-value-1234567890",
            "attempt": True,
            "status": "ready",
            "counts": {"assertionsExecuted": -1},
        }
        client = exporter.WeatherRouterLogGitClient(session, "token-for-archive")
        result = await client.async_export(snapshot, branch="main")
        stored = json.loads(base64.b64decode(session.upload["json"]["content"]))
        self.assertNotIn("example.org", result["path"])
        self.assertIsNone(stored["test"]["id"])
        self.assertIsNone(stored["test"]["runId"])
        self.assertIsNone(stored["test"]["attempt"])
        self.assertIsNone(stored["test"]["status"])
        self.assertIsNone(stored["test"]["counts"])

    async def test_source_repository_cannot_be_configured_as_export_target(self):
        session = FakeGitHubSession()
        with self.assertRaisesRegex(
            exporter.WeatherRouterLogExportError, "isolated private archive"
        ):
            exporter.WeatherRouterLogGitClient(
                session, "another-private-token",
                repository="TheDaimos/weather-router-dev",
                root=".weather-router/logs",
                require_private=False,
            )
        self.assertIsNone(session.upload)

    async def test_public_or_alternate_private_destination_is_rejected(self):
        for destination in ("TheDaimos/weather-router-dev", "TheDaimos/random-private"):
            with self.subTest(repository=destination):
                with self.assertRaises(exporter.WeatherRouterLogExportError):
                    exporter.WeatherRouterLogGitClient(
                        FakeGitHubSession(), "token",
                        repository=destination,
                        root="exports/weather-router",
                        require_private=True,
                    )

    def test_duplicate_archive_names_remain_unique(self):
        snap = self.snapshot()
        left = exporter._export_path(snap, root="exports/weather-router", archive=True)
        right = exporter._export_path(snap, root="exports/weather-router", archive=True)
        self.assertNotEqual(left, right)


class DefaultTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        file = ROOT / "websocket_api.py"
        source = file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {"_git_default_target", "_git_target", "_git_state"}
        subset = ast.Module(
            body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names],
            type_ignores=[],
        )
        cls.namespace = {
            "Any": object,
            "_ARCHIVE_REPO": "TheDaimos/Project-Log-And-Export",
            "_ARCHIVE_TOKEN_KEY": "log_archive_token",
            "_ARCHIVE_BRANCH_KEY": "log_archive_branch",
            "_DEFAULT_GIT_TARGET_KEY": "log_git_default_target",
            "LOG_GIT_REPOSITORY": "TheDaimos/weather-router-dev",
            "CONF_LOG_GIT_TOKEN": "log_git_token",
            "CONF_LOG_GIT_BRANCH": "log_git_branch",
            "LOG_GIT_ROOT": ".weather-router/logs",
            "WeatherRouterLogExportError": RuntimeError,
        }
        exec(compile(subset, str(file), "exec"), cls.namespace)
        cls.server_source = source
        cls.client_source = (ROOT / "frontend" / "weather-router-lab-log-export.js").read_text(encoding="utf-8")
        cls.provider_client_source = (
            ROOT / "frontend" / "weather-router-lab-diagnostics.js"
        ).read_text(encoding="utf-8")

    def test_existing_install_defaults_to_archive(self):
        entry = SimpleNamespace(data={})
        self.assertEqual(self.namespace["_git_default_target"](entry), "archive")
        self.assertTrue(self.namespace["_git_state"](entry, {"target": "archive"})["is_default"])

    def test_old_wr_selection_is_migrated_by_read_without_leaking_credentials(self):
        entry = SimpleNamespace(data={
            "log_git_default_target": "wr",
            "log_git_token": "wr-secret",
            "log_git_branch": "feature/global-hazard-feeds",
            "log_archive_token": "archive-secret",
            "log_archive_branch": "main",
        })
        self.assertEqual(self.namespace["_git_default_target"](entry), "archive")
        archive = self.namespace["_git_state"](entry, {"target": "archive"})
        retired = self.namespace["_git_state"](entry, {"target": "wr"})
        self.assertTrue(archive["configured"])
        self.assertTrue(archive["is_default"])
        self.assertEqual(archive["default_target"], "archive")
        self.assertFalse(retired["configured"])
        self.assertFalse(retired["is_default"])
        self.assertTrue(retired["retired"])
        self.assertTrue(retired["legacy_token_saved"])
        self.assertNotIn("wr-secret", str(retired))
        self.assertNotIn("archive-secret", str(archive))

    def test_wr_destination_is_rejected_by_server_target_selector(self):
        entry = SimpleNamespace(data={"log_git_default_target": "wr"})
        with self.assertRaisesRegex(RuntimeError, "not an authorized diagnostic destination"):
            self.namespace["_git_target"]({"target": "wr"}, entry)
        target = self.namespace["_git_target"]({}, entry)
        self.assertEqual(target[0], "TheDaimos/Project-Log-And-Export")
        self.assertEqual(target[3], "exports/weather-router")
        self.assertTrue(target[4])

    def test_backend_and_frontend_are_archive_only(self):
        self.assertIn('if target != "archive":', self.server_source)
        self.assertIn('Diagnostic destination is not isolated', self.server_source)
        self.assertIn('data.pop(CONF_LOG_GIT_TOKEN, None)', self.server_source)
        self.assertIn('_git_target(msg, entry)', self.server_source)
        self.assertIn('if (options.target && options.target !== "archive")', self.client_source)
        self.assertIn('const target = "archive";', self.client_source)
        self.assertIn('oldButton.disabled = true', self.client_source)
        self.assertIn('Git-WR gesperrt', self.client_source)
        self.assertIn('Als Standard-Repository verwenden', self.client_source)
        self.assertIn(
            "_wrGitExportSnapshot(this._diagnosticLastReport", self.provider_client_source
        )
        self.assertNotIn(
            'type: "weather_router/log_git_export"', self.provider_client_source
        )


if __name__ == "__main__":
    unittest.main()
