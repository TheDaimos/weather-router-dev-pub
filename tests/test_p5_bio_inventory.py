"""P5-BIO-10: static inventory contract for GBIF biological occurrence layers.

This test does not request GBIF resources and does not modify runtime routing.
It verifies the manifest against the actual provider, taxon catalogue and
public consumer capability mapping.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


INVENTORY = load_json("docs/p5_bio_inventory.v1.json")
CATALOG = load_json(
    "custom_components/weather_router/providers/biological_taxa.json"
)
MAPPING = load_json(
    "custom_components/weather_router/consumer_capability_map.json"
)
REGISTRY = load_json(
    "custom_components/weather_router/providers/registry.json"
)["providers"]
GBIF_PROVIDER_ID = "gbif_biodiversity"
PREFIX = "biological_hazards.occurrence."


class P5BioInventoryContractTest(unittest.TestCase):
    def test_schema_and_exact_baseline_counts(self) -> None:
        self.assertEqual(INVENTORY["schema_version"], 1)
        self.assertEqual(INVENTORY["stage"], "P5-BIO-10")
        self.assertEqual(CATALOG["schema_version"], 1)
        self.assertEqual(CATALOG["from_year"], 2000)
        self.assertEqual(INVENTORY["catalog"]["from_year"], 2000)
        self.assertEqual(INVENTORY["catalog"]["count"], 88)
        self.assertEqual(INVENTORY["public_contract"]["count"], 88)
        self.assertEqual(len(INVENTORY["taxa"]), 88)
        self.assertEqual(len(CATALOG["taxa"]), 88)
        self.assertEqual(len(MAPPING["public_capabilities"]), 227)
        self.assertEqual(INVENTORY["runtime"]["public_capabilities_total"], 227)

    def test_exact_provider_identity_and_opt_in_gate(self) -> None:
        rows = [
            x for x in REGISTRY if x["class"] == "GbifBiodiversityProvider"
        ]
        self.assertEqual(
            rows,
            [{
                "module": "gbif_biodiversity",
                "class": "GbifBiodiversityProvider",
                "domains": ["biological_hazards"],
                "default_enabled": False,
            }],
        )
        self.assertEqual(INVENTORY["provider"]["id"], GBIF_PROVIDER_ID)
        self.assertEqual(
            INVENTORY["provider"]["display_name"],
            "GBIF · Biologische Vorkommen",
        )
        self.assertFalse(INVENTORY["provider"]["default_enabled"])

    def test_taxon_catalog_is_a_lossless_inventory(self) -> None:
        original = CATALOG["taxa"]
        generated = INVENTORY["taxa"]
        self.assertEqual(
            [x["id"] for x in generated], [x["id"] for x in original]
        )
        self.assertEqual(len({x["id"] for x in generated}), 88)
        group_counts = {}
        for source, stored in zip(original, generated):
            for field in (
                "id", "name", "scientific_name", "group",
                "match_rank", "match_kingdom", "match_authorship",
            ):
                self.assertEqual(source.get(field), stored.get(field))
            expected_capability = "occurrence_density_" + source["id"]
            expected_public = PREFIX + source["id"] + ".density"
            self.assertEqual(stored["capability_id"], expected_capability)
            self.assertEqual(stored["public_id"], expected_public)
            group = source["group"]
            group_counts[group] = group_counts.get(group, 0) + 1
        self.assertEqual(INVENTORY["catalog"]["groups"], group_counts)

    def test_all_and_only_88_bio_public_capabilities_are_mapped(self) -> None:
        entries = INVENTORY["taxa"]
        mapped = MAPPING["providers"][GBIF_PROVIDER_ID]
        self.assertEqual(len(mapped), 88)
        actual_public = {
            k for k in MAPPING["public_capabilities"]
            if k.startswith("biological_hazards.")
        }
        self.assertEqual(
            actual_public, {x["public_id"] for x in entries}
        )
        self.assertEqual(
            set(mapped), {x["capability_id"] for x in entries}
        )
        for item in entries:
            self.assertEqual(
                mapped[item["capability_id"]], [item["public_id"]]
            )
            public = MAPPING["public_capabilities"][item["public_id"]]
            self.assertEqual(public["family"], "biological_occurrence_density")
            self.assertEqual(public["strategy"], "single")
            self.assertEqual(public["resource_types"], ["raster_tile"])

    def test_each_candidate_has_consistent_physical_source_time_contract(self) -> None:
        sources = {
            k: MAPPING[k]["providers"][GBIF_PROVIDER_ID]
            for k in (
                "capability_topic_assignments",
                "capability_resource_types",
                "capability_physical_semantics",
                "capability_source_semantics",
                "capability_observation_semantics",
                "capability_time_semantics",
                "capability_coverage_semantics",
            )
        }
        for mapping in sources.values():
            self.assertEqual(len(mapping), 88)
        for entry in INVENTORY["taxa"]:
            key = entry["capability_id"]
            self.assertEqual(
                sources["capability_topic_assignments"][key]["topics"],
                ["biological_hazards"],
            )
            self.assertEqual(
                sources["capability_resource_types"][key], "raster_tile"
            )
            physical = sources["capability_physical_semantics"][key]
            self.assertTrue(physical["numeric"])
            self.assertEqual(physical["quantity"], "occurrence_density")
            self.assertEqual(physical["unit_source"], "provider_capability")
            source = sources["capability_source_semantics"][key]
            self.assertEqual(source["data_origin"], "biodiversity_observation")
            self.assertEqual(
                source["measurement_method"], "occurrence_density_observation"
            )
            observed = sources["capability_observation_semantics"][key]
            self.assertEqual(observed["observation_kind"], "observation")
            temporal = sources["capability_time_semantics"][key]
            self.assertEqual(temporal["request_time_mode"], "latest")
            self.assertEqual(temporal["data_time"], "optional_runtime")
            self.assertEqual(temporal["valid_time"], "not_applicable")
            self.assertEqual(
                temporal["freshness_policy"], "consumer_max_age_optional"
            )

    def test_unknown_coverage_is_not_misrepresented_as_worldwide_safety(self) -> None:
        c = INVENTORY["public_contract"]
        self.assertEqual(c["coverage_scope"], "unknown")
        self.assertEqual(c["coverage_evidence"], "unknown")
        self.assertEqual(c["routing_authority"], "none")
        self.assertFalse(c["endpoint_reachability_is_coverage"])
        coverage = MAPPING["capability_coverage_semantics"][
            "providers"
        ][GBIF_PROVIDER_ID]
        for entry in INVENTORY["taxa"]:
            item = coverage[entry["capability_id"]]
            self.assertEqual(item["coverage_scope"], "unknown")
            self.assertEqual(item["coverage_evidence"], "unknown")
            self.assertEqual(item["routing_authority"], "none")
            self.assertFalse(item["endpoint_reachability_is_coverage"])
        guardrails = " ".join(INVENTORY["guardrails"])
        self.assertIn("Populationsdichte", guardrails)
        self.assertIn("Gefahrenwahrscheinlichkeit", guardrails)


if __name__ == "__main__":
    unittest.main()
