"""Independent static acceptance for P5-SECURITY-50."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "custom_components/weather_router/consumer_api.py").read_text(encoding="utf-8")
MAP = json.loads((ROOT / "custom_components/weather_router/consumer_capability_map.json").read_text(encoding="utf-8"))
DRAFT = json.loads((ROOT / "contracts/consumer_v1/capability-map.draft.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((ROOT / "custom_components/weather_router/providers/registry.json").read_text(encoding="utf-8"))["providers"]
POLICE = (ROOT / "custom_components/weather_router/providers/bbk_police.py").read_text(encoding="utf-8")
CONST = (ROOT / "custom_components/weather_router/const.py").read_text(encoding="utf-8")
LAB = (ROOT / "custom_components/weather_router/frontend/weather-router-lab.js").read_text(encoding="utf-8")
LOADER = (ROOT / "custom_components/weather_router/frontend/weather-router-lab-dev-loader.js").read_text(encoding="utf-8")


from wr_public_version_contract import assert_current_version_surfaces

class P5SecurityStaticAcceptance(unittest.TestCase):
    def test_01_catalog_227(self):
        self.assertEqual(len(MAP["public_capabilities"]), 227)

    def test_02_one_security_public_contract(self):
        self.assertEqual(
            [x for x in MAP["public_capabilities"] if x.startswith("security.")],
            ["security.public_warning.official"],
        )

    def test_03_exact_single_police_candidate(self):
        found = [(provider, cap) for provider, caps in MAP["providers"].items()
                 for cap, ids in caps.items() if "security.public_warning.official" in ids]
        self.assertEqual(found, [("bbk_police", "police_public_safety_warnings_germany")])

    def test_04_opt_in_only(self):
        match = [x for x in REGISTRY if x["module"] == "bbk_police"]
        self.assertEqual(len(match), 1)
        self.assertFalse(match[0]["default_enabled"])

    def test_05_compatibility_of_public_contract(self):
        c = MAP["public_capabilities"]["security.public_warning.official"]
        self.assertEqual(c["resource_types"], ["hazard_feed"])
        self.assertEqual(c["hazard_types"], ["public_safety"])

    def test_06_warning_origin_is_not_measurement(self):
        c = MAP["capability_source_semantics"]["providers"]["bbk_police"]["police_public_safety_warnings_germany"]
        self.assertEqual(c["data_origin"], "warning_authority")
        self.assertEqual(c["measurement_method"], "public_safety_warning_feed")
        o = MAP["capability_observation_semantics"]["providers"]["bbk_police"]["police_public_safety_warnings_germany"]
        self.assertEqual(o["observation_kind"], "warning_event")

    def test_07_guard_early_and_nonretryable(self):
        start = API.index("if (\n        public_id in _POINT_GEOMETRY_REQUIRED_PUBLIC_IDS")
        end = API.index("globally_enabled_candidates = [", start)
        block = API[start:end]
        for expected in ('context["type"] == "point"', 'result="rejected"',
                         'reason="requirements_not_met"', '"requirements_not_met"',
                         'retryable=False', 'return'):
            self.assertIn(expected, block)
        self.assertNotIn("candidate_attempt(", block)
        self.assertNotIn("candidate_provider_contact(", block)

    def test_08_context_supported_rejects_point(self):
        s = API[API.index("def _context_supported"):API.index("def _requirements_match")]
        self.assertIn("candidate.public_id in _SECURITY_PUBLIC_IDS", s)
        self.assertIn('context["type"] == "point"', s)
        self.assertIn("return False", s)

    def test_09_global_bbox_semantics_remain(self):
        self.assertIn('kwargs["bbox"] = (', API)
        self.assertIn('map_path="/police/mapData.json"', POLICE)
        self.assertIn("del latitude, longitude", POLICE)

    def test_10_no_automatic_official_crime_escalation(self):
        self.assertIn('return "public_safety"', (ROOT / "custom_components/weather_router/providers/bbk_warning_common.py").read_text(encoding="utf-8"))
        self.assertIn("does not infer attack/terrorism", (ROOT / "custom_components/weather_router/providers/bbk_warning_common.py").read_text(encoding="utf-8"))

    def test_11_draft_mirror_kept(self):
        self.assertEqual(MAP["public_capabilities"], DRAFT["public_capabilities"])
        self.assertEqual(MAP["providers"], DRAFT["providers"])

    def test_12_all_build_surfaces_synchronized(self):
        assert_current_version_surfaces(self, CONST, LAB, LOADER)


if __name__ == "__main__":
    unittest.main()
