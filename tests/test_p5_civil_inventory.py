"""Static contract test for P5-CIVIL-10 inventory."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = json.loads(
    (ROOT / "docs" / "p5_civil_inventory.v1.json").read_text(encoding="utf-8")
)
MAPPING = json.loads(
    (ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json").read_text(encoding="utf-8")
)
REGISTRY = json.loads(
    (ROOT / "custom_components" / "weather_router" / "providers" / "registry.json").read_text(encoding="utf-8")
)["providers"]
CONSUMER = (
    ROOT / "custom_components" / "weather_router" / "consumer_api.py"
).read_text(encoding="utf-8")


class P5CivilInventoryContractTest(unittest.TestCase):
    def test_exactly_one_public_civil_contract_exists(self) -> None:
        ids = sorted(
            item for item in MAPPING["public_capabilities"]
            if item.startswith("civil_protection.")
        )
        self.assertEqual(ids, ["civil_protection.warning.official"])
        self.assertEqual(INVENTORY["civil_public_capability_count"], 1)

    def test_public_contract_is_aggregate_hazard_feed(self) -> None:
        public = MAPPING["public_capabilities"]["civil_protection.warning.official"]
        self.assertEqual(public["strategy"], "aggregate")
        self.assertEqual(public["resource_types"], ["hazard_feed"])

    def test_exact_four_candidates_exist(self) -> None:
        expected = {
            "bbk_mowas/civil_protection_warnings_germany",
            "nina_flood/flood_information_germany",
            "nina_katwarn/katwarn_public_warnings",
            "nina_biwapp/biwapp_public_warnings",
        }
        found = set()
        for provider_id, capabilities in MAPPING["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if "civil_protection.warning.official" in public_ids:
                    found.add(f"{provider_id}/{capability_id}")
        self.assertEqual(found, expected)

    def test_all_four_candidates_are_default_disabled(self) -> None:
        by_class = {
            item["class"]: item
            for item in REGISTRY
            if item["class"] in {
                "BbkMowasProvider",
                "NinaFloodProvider",
                "NinaKatwarnProvider",
                "NinaBiwappProvider",
            }
        }
        self.assertEqual(len(by_class), 4)
        for item in by_class.values():
            self.assertFalse(item["default_enabled"])

    def test_nina_flood_is_explicitly_cross_domain(self) -> None:
        item = next(
            row for row in REGISTRY if row["class"] == "NinaFloodProvider"
        )
        self.assertEqual(
            item["domains"],
            ["natural_hazards", "civil_protection"],
        )

    def test_shared_source_and_coverage_semantics_match(self) -> None:
        source = MAPPING["capability_source_semantics"]["providers"]
        observation = MAPPING["capability_observation_semantics"]["providers"]
        coverage = MAPPING["capability_coverage_semantics"]["providers"]
        for entry in INVENTORY["candidates"]:
            provider_id, capability_id = entry["key"].split("/", 1)
            self.assertEqual(
                source[provider_id][capability_id]["data_origin"],
                "warning_authority",
            )
            self.assertEqual(
                source[provider_id][capability_id]["measurement_method"],
                "civil_protection_warning_feed",
            )
            self.assertEqual(
                observation[provider_id][capability_id]["observation_kind"],
                "warning_event",
            )
            self.assertEqual(
                coverage[provider_id][capability_id]["coverage_scope"],
                "dynamic",
            )
            self.assertEqual(
                coverage[provider_id][capability_id]["coverage_evidence"],
                "runtime_event_geometry",
            )
            self.assertEqual(
                coverage[provider_id][capability_id]["routing_authority"],
                "context_filter",
            )
            self.assertFalse(
                coverage[provider_id][capability_id]["endpoint_reachability_is_coverage"]
            )

    def test_aggregate_preserves_source_provenance_without_cross_channel_dedup(self) -> None:
        self.assertIn('event["source_event_id"] = source_event_id', CONSUMER)
        self.assertIn('event["source_ref"] = candidate.provider.id', CONSUMER)
        self.assertIn(
            'event["id"] = f"{candidate.provider.id}:{source_event_id}"',
            CONSUMER,
        )
        aggregation = INVENTORY["aggregation"]
        self.assertTrue(aggregation["preserves_source_provenance"])
        self.assertFalse(aggregation["cross_channel_content_deduplication"])

    def test_core_invariants_are_recorded(self) -> None:
        invariants = set(INVENTORY["invariants"])
        for item in (
            "Warning channel is not identical to a physical incident.",
            "Multiple source warnings do not automatically mean multiple physical hazards.",
            "Aggregation must not semantically escalate warnings.",
            "Source provenance must be preserved.",
            "Endpoint reachability is not coverage proof.",
        ):
            self.assertIn(item, invariants)


if __name__ == "__main__":
    unittest.main()
