"""P6-040: no provider identity may determine semantic routing score."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "custom_components/weather_router/consumer_routing_policy.py"
spec = importlib.util.spec_from_file_location("wr_p6040_routing_policy", POLICY)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class P6040ProviderNeutralScoring(unittest.TestCase):
    def setUp(self):
        self.public_id = "weather.precipitation.layer"
        self.mapping = {
            "public_capabilities": {
                self.public_id: {
                    "routing_preferences": {
                        "observation_kinds": ["observation", "forecast"],
                        "quantities": ["precipitation_rate", "radar_reflectivity"],
                        "data_origins": ["radar", "satellite"],
                    }
                }
            }
        }
        self.semantics = {
            "observation_kind": "observation",
            "quantity": "precipitation_rate",
            "data_origin": "radar",
        }

    def test_score_only_uses_normalized_semantics(self):
        one = module.candidate_score(self.mapping, self.public_id, self.semantics)
        other = module.candidate_score(
            self.mapping,
            self.public_id,
            {**self.semantics, "provider_id": "some_other_provider", "source_provider": "another"},
        )
        self.assertEqual(one, other)

    def test_excluded_provider_is_not_a_scoring_preference(self):
        first = module.candidate_score(self.mapping, self.public_id, self.semantics)
        second = module.candidate_score(
            {**self.mapping, "excluded_providers": ["provider_a"], "preferred_provider": "provider_b"},
            self.public_id,
            self.semantics,
        )
        self.assertEqual(first, second)

    def test_semantics_change_score_without_provider_id(self):
        best = module.candidate_score(self.mapping, self.public_id, self.semantics)
        alternative = module.candidate_score(
            self.mapping,
            self.public_id,
            {**self.semantics, "observation_kind": "forecast"},
        )
        self.assertNotEqual(best, alternative)

if __name__ == "__main__":
    unittest.main()
