"""Architecture invariants for WeatherRouter provider-neutral routing."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "weather_router"
MAP_PATH = COMPONENT / "consumer_capability_map.json"
POLICY_PATH = COMPONENT / "consumer_routing_policy.py"
PROFILES_PATH = COMPONENT / "consumer_profiles.py"
PROFILE_SCHEMA_PATH = ROOT / "contracts" / "consumer_v1" / "consumer-profile.schema.json"
AUDIT_PATH = ROOT / "docs" / "consumer_routing_audit.v1.json"

SPECIALIZED_PRECIPITATION_IDS = {
    "weather.radar.precipitation",
    "weather.radar.precipitation.quality_checked",
    "weather.radar.reflectivity",
    "weather.satellite.precipitation_rate",
    "weather.model.precipitation_1h.layer",
}


class RoutingInvariantTest(unittest.TestCase):
    """P1-090 makes non-negotiable routing rules fail closed in CI."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    def _public_candidates(self) -> dict[str, list[tuple[str, str]]]:
        result: dict[str, list[tuple[str, str]]] = {}
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                for public_id in public_ids:
                    result.setdefault(public_id, []).append((provider_id, capability_id))
        return result

    def test_scoring_has_no_provider_priority_axis(self) -> None:
        source = POLICY_PATH.read_text(encoding="utf-8")
        score_source = source.split("def candidate_score(", 1)[1]
        self.assertNotIn("provider_id", score_source)
        self.assertNotIn("provider_priority", score_source)
        self.assertNotIn("preferred_provider", score_source)
        self.assertIn('rank("observation_kinds", "observation_kind")', score_source)
        self.assertIn('rank("quantities", "quantity")', score_source)
        self.assertIn('rank("data_origins", "data_origin")', score_source)

    def test_profiles_can_only_restrict_not_prioritize_or_force_providers(self) -> None:
        source = PROFILES_PATH.read_text(encoding="utf-8")
        schema = json.loads(PROFILE_SCHEMA_PATH.read_text(encoding="utf-8"))
        serialized_schema = json.dumps(schema, sort_keys=True)

        for forbidden in (
            "preferred_providers",
            "provider_priority",
            "provider_order",
            "forced_provider",
            "required_provider",
        ):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, serialized_schema)

        self.assertIn('"excluded_providers"', source)
        self.assertIn("provider_id not in set(profile.get", source)
        self.assertIn("never enable a globally disabled provider/domain", source)

    def test_specialized_ids_remain_available_next_to_shared_intent(self) -> None:
        public = set(self.mapping["public_capabilities"])
        self.assertIn("weather.precipitation.layer", public)
        self.assertTrue(SPECIALIZED_PRECIPITATION_IDS <= public)

    def test_every_multi_candidate_public_capability_has_full_candidate_semantics(self) -> None:
        public_candidates = self._public_candidates()
        multi = {key: value for key, value in public_candidates.items() if len(value) > 1}
        self.assertTrue(multi)

        contracts = (
            "capability_topic_assignments",
            "capability_resource_types",
            "capability_physical_semantics",
            "capability_source_semantics",
            "capability_observation_semantics",
            "capability_time_semantics",
            "capability_coverage_semantics",
        )
        for public_id, candidates in multi.items():
            for provider_id, capability_id in candidates:
                for contract_name in contracts:
                    provider_map = self.mapping[contract_name]["providers"][provider_id]
                    self.assertIn(
                        capability_id,
                        provider_map,
                        f"{public_id}: {provider_id}/{capability_id} missing {contract_name}",
                    )

                source = self.mapping["capability_source_semantics"]["providers"][provider_id][capability_id]
                observation = self.mapping["capability_observation_semantics"]["providers"][provider_id][capability_id]
                self.assertNotEqual(source["data_origin"], "unspecified")
                self.assertNotEqual(source["measurement_method"], "unspecified")
                self.assertNotEqual(observation["observation_kind"], "unspecified")

    def test_every_candidate_has_topic_and_resource_compatible_public_mapping(self) -> None:
        topics = self.mapping["capability_topic_assignments"]["providers"]
        resources = self.mapping["capability_resource_types"]["providers"]
        public = self.mapping["public_capabilities"]

        count = 0
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                topic = topics[provider_id][capability_id]
                self.assertEqual(topic["classification"], "topic_mapped")
                self.assertTrue(topic["topics"])

                candidate_resource = resources[provider_id][capability_id]
                for public_id in public_ids:
                    self.assertIn(candidate_resource, public[public_id]["resource_types"])
                count += 1
        self.assertEqual(count, 280)

    def test_shared_precipitation_intent_is_resource_compatible_and_specialized(self) -> None:
        candidates = self._public_candidates()["weather.precipitation.layer"]
        self.assertEqual(len(candidates), 5)
        resources = self.mapping["capability_resource_types"]["providers"]
        self.assertEqual(
            {resources[provider_id][capability_id] for provider_id, capability_id in candidates},
            {"raster_tile"},
        )
        contract = self.mapping["public_capabilities"]["weather.precipitation.layer"]["intent_contract"]
        self.assertEqual(contract["resource_type"], "raster_tile")
        self.assertTrue(contract["render_interchangeable"])
        self.assertFalse(contract["numeric_interchangeable"])

    def test_machine_audit_and_runtime_mapping_are_structurally_synchronized(self) -> None:
        sync = self.audit["runtime_mapping_sync"]
        self.assertEqual(sync["status"], "synchronized")
        self.assertEqual(sync["core_provider_count"], len(self.mapping["providers"]))
        # The routing audit is a dated baseline snapshot. Later additive phases
        # may grow the runtime catalog without rewriting historical audit evidence.
        self.assertLessEqual(
            sync["internal_capability_count"],
            sum(len(capabilities) for capabilities in self.mapping["providers"].values()),
        )
        self.assertLessEqual(
            sync["public_capability_count"],
            len(self.mapping["public_capabilities"]),
        )
        self.assertTrue(
            set(sync["public_capability_ids"]).issubset(self.mapping["public_capabilities"])
        )

        audit_rows = {
            row["public_capability"]: row
            for row in self.audit["public_capabilities"]
        }
        self.assertTrue(set(audit_rows).issubset(self.mapping["public_capabilities"]))

        runtime_candidates = self._public_candidates()
        for public_id, row in audit_rows.items():
            audited = {
                (candidate["provider_id"], candidate["internal_capability"])
                for candidate in row["candidates"]
            }
            self.assertEqual(audited, set(runtime_candidates[public_id]), public_id)
            self.assertEqual(row["candidate_count"], len(runtime_candidates[public_id]))


if __name__ == "__main__":
    unittest.main()
