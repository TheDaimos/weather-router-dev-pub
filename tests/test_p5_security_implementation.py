"""Regression checks for P5-SECURITY-40 implementation."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "custom_components/weather_router/consumer_api.py").read_text(encoding="utf-8")
MAP = json.loads((ROOT / "custom_components/weather_router/consumer_capability_map.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((ROOT / "custom_components/weather_router/providers/registry.json").read_text(encoding="utf-8"))["providers"]
POLICE = (ROOT / "custom_components/weather_router/providers/bbk_police.py").read_text(encoding="utf-8")
CONST = (ROOT / "custom_components/weather_router/const.py").read_text(encoding="utf-8")
LAB = (ROOT / "custom_components/weather_router/frontend/weather-router-lab.js").read_text(encoding="utf-8")
LOADER = (ROOT / "custom_components/weather_router/frontend/weather-router-lab-dev-loader.js").read_text(encoding="utf-8")


from wr_public_version_contract import assert_current_version_surfaces

class P5SecurityImplementationTest(unittest.TestCase):
    def test_public_contract_and_candidate_stay_stable(self):
        self.assertEqual(len(MAP["public_capabilities"]), 227)
        self.assertEqual(MAP["providers"]["bbk_police"]["police_public_safety_warnings_germany"], ["security.public_warning.official"])
        public = MAP["public_capabilities"]["security.public_warning.official"]
        self.assertEqual(public["resource_types"], ["hazard_feed"])
        self.assertEqual(public["hazard_types"], ["public_safety"])

    def test_police_provider_remains_opt_in(self):
        row = next(row for row in REGISTRY if row["module"] == "bbk_police")
        self.assertFalse(row["default_enabled"])
        self.assertEqual(row["domains"], ["security"])

    def test_point_guard_is_explicit_and_precedes_provider_selection(self):
        self.assertIn('"security.public_warning.official"', API)
        context_block = API[API.index("def _context_supported"):API.index("def _requirements_match")]
        self.assertIn("candidate.public_id in _SECURITY_PUBLIC_IDS", context_block)
        self.assertIn('context["type"] == "point"', context_block)
        guard = API.index('public_id in _POINT_GEOMETRY_REQUIRED_PUBLIC_IDS')
        eligible = API.index('globally_enabled_candidates = [', guard)
        block = API[guard:eligible]
        for token in ('context["type"] == "point"', 'result="rejected"', 'reason="requirements_not_met"', 'retryable=False', 'return'):
            self.assertIn(token, block)
        self.assertNotIn("candidate_attempt(", block)
        self.assertNotIn("candidate_provider_contact(", block)
        self.assertIn("Sicherheits-Point-Abfragen benötigen", block)

    def test_warning_semantics_and_geography_remain_correct(self):
        sem = MAP["capability_source_semantics"]["providers"]["bbk_police"]["police_public_safety_warnings_germany"]
        self.assertEqual(sem, {"data_origin": "warning_authority", "measurement_method": "public_safety_warning_feed"})
        kind = MAP["capability_observation_semantics"]["providers"]["bbk_police"]["police_public_safety_warnings_germany"]
        self.assertEqual(kind["observation_kind"], "warning_event")
        self.assertIn('map_path="/police/mapData.json"', POLICE)
        self.assertIn("del latitude, longitude", POLICE)
        self.assertIn('kwargs["bbox"] = (', API)

    def test_version_surfaces_are_synchronized(self):
        assert_current_version_surfaces(self, CONST, LAB, LOADER)


if __name__ == "__main__":
    unittest.main()
