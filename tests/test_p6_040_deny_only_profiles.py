"""P6-040: direct deny-only Consumer Profile regression tests.

Uses the actual policy module without Home Assistant imports or network calls.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_components/weather_router/consumer_profiles.py"
CONTRACT = ROOT / "custom_components/weather_router/consumer_capability_map.json"
spec = importlib.util.spec_from_file_location("p6040_profiles", MODULE)
profiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profiles)


class P6040DenyOnlyProfiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.public_ids = list(cls.mapping["public_capabilities"])
        cls.providers = list(cls.mapping["providers"])

    def test_provider_deny_does_not_grant(self):
        candidate = self.providers[0]
        self.assertFalse(profiles.profile_allows_provider({"excluded_providers": [candidate]}, candidate))
        self.assertTrue(profiles.profile_allows_provider({"excluded_providers": [candidate]}, self.providers[1]))
        self.assertTrue(profiles.profile_allows_provider(None, candidate))

    def test_candidate_classes_deny_with_specific_reasons(self):
        policy = {"excluded_data_origins": ["satellite"],
                  "excluded_measurement_methods": ["radar_reflectivity"],
                  "excluded_observation_kinds": ["forecast"]}
        vectors = [
            ({"data_origin": "satellite"}, "profile_data_origin_filtered"),
            ({"measurement_method": "radar_reflectivity"}, "profile_measurement_method_filtered"),
            ({"observation_kind": "forecast"}, "profile_observation_kind_filtered"),
        ]
        for semantics, reason in vectors:
            with self.subTest(reason=reason):
                self.assertEqual(profiles.profile_allows_candidate(policy, semantics), (False, reason))
        self.assertEqual(profiles.profile_allows_candidate(policy, {"data_origin": "radar", "observation_kind": "observation"}), (True, None))

    def test_catalog_domain_and_capability_limits(self):
        for public_id in self.public_ids:
            with self.subTest(public_id=public_id):
                own_domain = public_id.split(".", 1)[0]
                other_domain = next((x.split(".", 1)[0] for x in self.public_ids if x.split(".", 1)[0] != own_domain), None)
                if other_domain:
                    allowed, reason = profiles.profile_allows_capability(
                        {"enabled": True, "allowed_domains": [other_domain]}, self.mapping, public_id)
                    self.assertEqual((allowed, reason), (False, "profile_domain_filtered"))
        selected = self.public_ids[0]
        other = self.public_ids[1]
        self.assertEqual(profiles.profile_allows_capability(
            {"enabled": True, "allowed_capabilities": [selected]}, self.mapping, other),
            (False, "profile_capability_filtered"))

    def test_disabled_profile_blocks_and_unprofiled_is_unchanged(self):
        public_id = self.public_ids[0]
        self.assertEqual(profiles.profile_allows_capability({"enabled": False}, self.mapping, public_id), (False, "profile_disabled"))
        self.assertEqual(profiles.profile_allows_capability(None, self.mapping, public_id), (True, None))

    def test_event_intersection_never_expands_request(self):
        req = {"hazard_types": {"hail", "flood"}, "severities": {"severe"}}
        policy = {"allowed_hazard_types": ["hail"], "allowed_severities": ["severe", "extreme"]}
        merged, blocked = profiles.apply_profile_event_filter(policy, req)
        self.assertFalse(blocked)
        self.assertEqual(merged["hazard_types"], {"hail"})
        self.assertEqual(merged["severities"], {"severe"})
        _, blocked = profiles.apply_profile_event_filter(
            {"allowed_hazard_types": ["tornado"]}, req)
        self.assertTrue(blocked)

    def test_reject_provider_priority_fields(self):
        base = {"name": "Test", "enabled": True}
        for field in ("preferred_provider", "provider_priority", "preferred_providers", "provider_order", "force_provider"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    profiles.normalize_consumer_profile("p6040", {**base, field: "any"})

    def test_every_catalog_capability_has_defined_domain(self):
        for public_id in self.public_ids:
            with self.subTest(public_id=public_id):
                self.assertIn(".", public_id)
                self.assertNotEqual(public_id.split(".", 1)[0], "")


if __name__ == "__main__":
    unittest.main()
