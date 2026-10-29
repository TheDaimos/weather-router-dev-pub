"""Regression contract for the public OPERA JSON/Export2Git UI."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "custom_components/weather_router/frontend/weather-router-lab.js"
API = ROOT / "custom_components/weather_router/websocket_api.py"
CONST = ROOT / "custom_components/weather_router/const.py"


class OperaExportContractTests(unittest.TestCase):
    def test_opera_export_controls_and_live_snapshot(self):
        js = FRONTEND.read_text(encoding="utf-8")
        for required in (
            'id="opera-json"',
            'id="opera-git"',
            'async _operaExportSnapshot()',
            'async _exportOperaJson()',
            'async _exportOperaGit()',
            'type:"weather_router/opera_status"',
            'schema:"weather_router.opera_status.v1"',
            'captured_at_utc:new Date().toISOString()',
        ):
            with self.subTest(required=required):
                self.assertIn(required, js)

    def test_git_uses_existing_private_archive_only(self):
        js = FRONTEND.read_text(encoding="utf-8")
        api = API.read_text(encoding="utf-8")
        self.assertIn('type:"weather_router/log_git_export",target:"archive",snapshot', js)
        self.assertIn('"weather_router.opera_status.v1"', api)
        self.assertIn('if not isinstance(opera, dict) or not isinstance(opera.get("products"), dict)', api)
        self.assertIn('if repo != _ARCHIVE_REPO or not private:', api)
        self.assertIn('if not info["private"]:', api)

    def test_version_bumped(self):
        const = CONST.read_text(encoding="utf-8")
        self.assertIn('DEV_BUILD_VERSION: Final = "0.10.164"', const)
        self.assertIn('DEV_LOADER_REV: Final = "0.10-loader-167"', const)


if __name__ == "__main__":
    unittest.main()
