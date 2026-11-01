"""P6-040: verify profile restrictions over every public and internal Core path.

The tests use the shipped registry and actual policy implementations. No provider
I/O, personal data or HA runtime is needed.
"""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "custom_components/weather_router"


def module_from_file(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, CORE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profiles = module_from_file("p6040_profile_matrix", "consumer_profiles.py")
routing = module_from_file("p6040_semantics_matrix", "consumer_routing_policy.py")


class P6040CompleteCoreMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = json.loads((CORE / "consumer_capability_map.json").read_text(encoding="utf-8"))
        cls.public_ids = cls.mapping["public_capabilities"]
        cls.provider_map = cls.mapping["providers"]

    def test_restrictions_on_every_public_id(self):
        all_ids = list(self.public_ids)
        self.assertGreater(len(all_ids), 0)
        for public_id, meta in self.public_ids.items():
            domain = public_id.split(".", 1)[0]
            family = meta.get("family")
            with self.subTest(public_id=public_id):
                self.assertEqual(profiles.profile_allows_capability(None, self.mapping, public_id), (True, None))
                self.assertEqual(
                    profiles.profile_allows_capability(
                        {"enabled": True, "allowed_domains": [domain]}, self.mapping, public_id),
                    (True, None))
                self.assertEqual(
                    profiles.profile_allows_capability(
                        {"enabled": True, "allowed_capabilities": [public_id]}, self.mapping, public_id),
                    (True, None))
                self.assertEqual(
                    profiles.profile_allows_capability(
                        {"enabled": True, "allowed_capabilities": ["synthetic.nonexistent"]},
                        self.mapping, public_id),
                    (False, "profile_capability_filtered"))
                if family:
                    self.assertEqual(
                        profiles.profile_allows_capability(
                            {"enabled": True, "allowed_families": [family]}, self.mapping, public_id),
                        (True, None))
                for field, metadata_key, reason in (
                    ("allowed_phenomena", "phenomena", "profile_phenomenon_filtered"),
                    ("allowed_hazard_types", "hazard_types", "profile_hazard_filtered"),
                ):
                    tags = set(meta.get(metadata_key, []) or [])
                    if tags:
                        self.assertEqual(
                            profiles.profile_allows_capability(
                                {"enabled": True, field: ["synthetic_nonmatching"]}, self.mapping, public_id),
                            (False, reason))
                    else:
                        self.assertEqual(
                            profiles.profile_allows_capability(
                                {"enabled": True, field: ["synthetic_nonmatching"]}, self.mapping, public_id),
                            (True, None))

    def test_denial_on_every_internal_candidate(self):
        seen = 0
        for provider_id, capabilities in self.provider_map.items():
            for internal_id, public_ids in capabilities.items():
                for public_id in public_ids:
                    semantics = routing.normalized_candidate_semantics(
                        self.mapping, public_id, provider_id, internal_id,
                        source_class=None, unit=None)
                    with self.subTest(provider=provider_id, capability=internal_id, public_id=public_id):
                        self.assertTrue(profiles.profile_allows_provider(None, provider_id))
                        self.assertFalse(profiles.profile_allows_provider(
                            {"excluded_providers": [provider_id]}, provider_id))
                        self.assertEqual(profiles.profile_allows_candidate(None, semantics), (True, None))
                        for field, semantic_key, reason in (
                            ("excluded_data_origins", "data_origin", "profile_data_origin_filtered"),
                            ("excluded_measurement_methods", "measurement_method", "profile_measurement_method_filtered"),
                            ("excluded_observation_kinds", "observation_kind", "profile_observation_kind_filtered"),
                        ):
                            value = semantics[semantic_key]
                            self.assertIsInstance(value, str)
                            self.assertEqual(
                                profiles.profile_allows_candidate({field: [value]}, semantics),
                                (False, reason))
                        seen += 1
        self.assertEqual(seen, sum(len(ids) for caps in self.provider_map.values() for ids in caps.values()))


if __name__ == "__main__":
    unittest.main()
