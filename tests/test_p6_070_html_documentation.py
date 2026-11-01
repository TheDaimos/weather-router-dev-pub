"""P6-070: public HTML help must match current shipped Consumer core contract."""
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "custom_components/weather_router/frontend/weather-router-help.html"
MAP = ROOT / "custom_components/weather_router/consumer_capability_map.json"
REGISTRY = ROOT / "custom_components/weather_router/providers/registry.json"


class P6070HtmlDocumentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = HTML.read_text(encoding="utf-8")
        cls.mapping = json.loads(MAP.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_core_numbers_and_current_build_are_consistent(self):
        providers = len(self.mapping["providers"])
        public = len(self.mapping["public_capabilities"])
        self.assertEqual(providers, len(self.registry["providers"]))
        self.assertEqual(providers, 38)
        self.assertEqual(public, 227)
        self.assertIn(f"{providers} Core-Provider", self.page)
        self.assertIn(f"{public} Public-Capabilities", self.page)
        # Read the source-of-truth version markers instead of asserting a stale build.
        core = (ROOT / "custom_components/weather_router/const.py").read_text(encoding="utf-8")
        lab = (ROOT / "custom_components/weather_router/frontend/weather-router-lab.js").read_text(encoding="utf-8")
        loader_js = (ROOT / "custom_components/weather_router/frontend/weather-router-lab-dev-loader.js").read_text(encoding="utf-8")
        build_match = re.search(r'^DEV_BUILD_VERSION:\s*Final\s*=\s*"([^"]+)"', core, re.M)
        loader_match = re.search(r'^DEV_LOADER_REV:\s*Final\s*=\s*"0\.10-loader-(\d+)"', core, re.M)
        self.assertIsNotNone(build_match)
        self.assertIsNotNone(loader_match)
        build, loader = build_match.group(1), loader_match.group(1)
        self.assertIn(f'<span class="badge">WR {build} DEV</span>', self.page)
        self.assertIn(f'<span class="badge">Loader {loader}</span>', self.page)
        self.assertIn(f'const WR_LAB_BUILD_VERSION = "{build}"', lab)
        self.assertIn(f'const WR_LAB_BUILD_VERSION = "{build}"', loader_js)
        self.assertIn(f'const LOADER_REV = "0.10-loader-{loader}"', loader_js)
        self.assertNotIn("WR 0.10.77 DEV", self.page)
        self.assertIn("P6-070", self.page)
        self.assertIn("P6-080", self.page)

    def test_provider_table_and_html_structure(self):
        area = self.page.split('id="provider"', 1)[1].split("</tbody>", 1)[0]
        self.assertEqual(len(re.findall(r"<tr><td>", area)), len(self.registry["providers"]))
        for tag in ("article", "section", "main"):
            self.assertEqual(
                len(re.findall(rf"<{tag}(?:\s|>)", self.page)),
                len(re.findall(rf"</{tag}>", self.page)),
            )

    def test_do_not_publish_private_hardware_or_user_locations(self):
        for forbidden in ("private_home_location_placeholder", "private_identifier_placeholder", "api_key=", "access_token="):
            self.assertNotIn(forbidden, self.page)


if __name__ == "__main__":
    unittest.main()
