"""P5-BIO-20 semantic contract tests (no remote GBIF access)."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


SEMANTICS = load("docs/p5_bio_semantics.v1.json")
INVENTORY = load("docs/p5_bio_inventory.v1.json")
MAPPING = load("custom_components/weather_router/consumer_capability_map.json")
PROVIDER = (
    ROOT / "custom_components/weather_router/providers/gbif_biodiversity.py"
).read_text(encoding="utf-8")
CONSUMER = (
    ROOT / "custom_components/weather_router/consumer_api.py"
).read_text(encoding="utf-8")
TAXA = load("custom_components/weather_router/providers/biological_taxa.json")


class P5BioSemanticsTest(unittest.TestCase):
    def test_semantics_are_specialized_and_not_a_fabricated_shared_intent(self):
        contract = SEMANTICS["contract"]
        self.assertEqual(contract["public_count"], 88)
        self.assertEqual(contract["family"], "biological_occurrence_density")
        self.assertEqual(contract["strategy"], "single")
        self.assertEqual(contract["resource_type"], "raster_tile")
        self.assertTrue(contract["all_specialized"])
        self.assertFalse(contract["new_shared_intent"])
        public = {
            k: v for k, v in MAPPING["public_capabilities"].items()
            if k.startswith("biological_hazards.")
        }
        self.assertEqual(len(public), 88)
        self.assertEqual(set(public), {x["public_id"] for x in INVENTORY["taxa"]})
        for v in public.values():
            self.assertEqual(v["family"], contract["family"])
            self.assertEqual(v["strategy"], contract["strategy"])
            self.assertEqual(v["resource_types"], [contract["resource_type"]])

    def test_density_never_claims_population_or_harm_probability(self):
        physical = SEMANTICS["physical_semantics"]
        self.assertEqual(physical["quantity"], "occurrence_density")
        self.assertEqual(physical["observation_kind"], "observation")
        self.assertEqual(physical["data_origin"], "biodiversity_observation")
        self.assertEqual(physical["source_class"], "biodiversity_occurrence")
        self.assertEqual(
            physical["measurement_method"], "occurrence_density_observation"
        )
        self.assertEqual(physical["unit"], "Vorkommensnachweise pro Rasterzelle")
        for prop in (
            "population_density", "population_size", "current_presence",
            "encounter_probability", "hazard_probability",
            "infection_probability", "official_hazard_warning",
        ):
            self.assertIs(physical[prop], False, prop)
        for item in INVENTORY["taxa"]:
            public_id = item["public_id"]
            self.assertIn("keine", MAPPING["public_capabilities"][public_id]["note"].lower())
        self.assertIn('"population_density": False', PROVIDER)
        self.assertIn('"risk_probability": False', PROVIDER)

    def test_point_and_bbox_are_display_requests_not_local_detection(self):
        contract = SEMANTICS["context_contract"]
        self.assertEqual(contract["global"], "allowed_map_layer_only")
        self.assertEqual(
            contract["bbox"],
            "allowed_as_map_viewport_not_server_side_bbox_filter",
        )
        self.assertEqual(
            contract["point"],
            "allowed_as_map_layer_request_not_point_presence_or_proximity_analysis",
        )
        self.assertEqual(contract["nearby"], "no_implicit_nearby_radius_or_point_in_geometry")
        self.assertIn('if render_mode == "raster_tile":', CONSUMER)
        self.assertIn('return ["global", "point", "bbox"]', CONSUMER)
        self.assertIn("result = await fetch(hass, candidate.capability.id)", CONSUMER)
        self.assertIn("async def async_get_map_layer(", PROVIDER)
        self.assertNotIn("latitude:", PROVIDER.split("async def async_get_map_layer(", 1)[1].split("async def async_get_taxon_layer(", 1)[0])
        self.assertNotIn("longitude:", PROVIDER.split("async def async_get_map_layer(", 1)[1].split("async def async_get_taxon_layer(", 1)[0])

    def test_coverage_semantics_same_for_each_of_88_candidates(self):
        expected = SEMANTICS["coverage"]
        keys = (
            "coverage_scope", "coverage_evidence", "routing_authority",
            "coordinate_space", "endpoint_reachability_is_coverage",
        )
        provider = MAPPING["capability_coverage_semantics"]["providers"]["gbif_biodiversity"]
        self.assertEqual(len(provider), 88)
        for item in INVENTORY["taxa"]:
            record = provider[item["capability_id"]]
            for key in keys:
                self.assertEqual(record[key], expected[key], item["capability_id"])
        self.assertFalse(expected["global_map_url_is_global_presence_proof"])
        self.assertFalse(expected["no_records_means_absence"])
        self.assertFalse(expected["successful_tile_url_is_tile_content_proof"])

    def test_time_is_historical_observation_not_current_forecast(self):
        time = SEMANTICS["time"]
        self.assertEqual(time["from_year"], TAXA["from_year"])
        self.assertEqual(time["request_time_mode"], "latest")
        self.assertEqual(time["valid_time"], "not_applicable")
        self.assertFalse(time["observed_absence_is_forecast"])
        self.assertIn('"year": f"{from_year},{current_year}"', PROVIDER)
        self.assertIn('"frame_time": None', PROVIDER)

    def test_taxonomic_overlap_and_admin_search_boundary(self):
        taxon = SEMANTICS["taxon_semantics"]
        self.assertTrue(taxon["overlapping_taxa_possible"])
        self.assertFalse(taxon["additive_species_and_parent_group_counts"])
        self.assertFalse(taxon["arbitrary_admin_taxon_is_public"])
        self.assertIn("async def async_get_taxon_layer(", PROVIDER)
        self.assertIn("dynamic_taxon_search", PROVIDER)
        self.assertEqual(
            set(MAPPING["providers"]["gbif_biodiversity"]),
            {x["capability_id"] for x in INVENTORY["taxa"]},
        )
        self.assertNotIn(
            "dynamic_taxon_search", MAPPING["providers"]["gbif_biodiversity"]
        )
        for prop in (
            "preserve_requested_scientific_name", "preserve_matched_scientific_name",
            "preserve_taxon_key", "preserve_match_confidence_if_present",
        ):
            self.assertTrue(taxon[prop])

    def test_raster_provider_preserves_source_and_quality_metadata(self):
        mapping = SEMANTICS["map_provenance"]
        self.assertEqual(mapping["provider_url_host"], "api.gbif.org")
        self.assertEqual(mapping["raster_projection"], "EPSG:3857")
        self.assertEqual(mapping["quality_filter"], "hasGeospatialIssue=false")
        self.assertTrue(mapping["attribution_required"])
        self.assertTrue(mapping["underlying_dataset_licences_must_be_respected"])
        self.assertTrue(mapping["recording_bias_warning_required"])
        self.assertTrue(mapping["tiles_are_raster_not_event_geometries"])
        self.assertIn('"render_mode": "raster_tile"', PROVIDER)
        self.assertIn('"taxon_key": match["taxon_key"]', PROVIDER)
        self.assertIn('"match_confidence": match["confidence"]', PROVIDER)
        self.assertIn('"hasGeospatialIssue": "false"', PROVIDER)
        self.assertIn("_TERMS_URL", PROVIDER)

    def test_no_warning_aggregation_or_false_negative_semantics(self):
        isolation = SEMANTICS["isolation"]
        self.assertTrue(isolation["no_cross_taxon_aggregation"])
        self.assertTrue(isolation["no_weather_hazard_or_civil_warning_fallback"])
        self.assertTrue(isolation["no_auto_disease_outbreak_inference"])
        self.assertTrue(isolation["no_automatic_poisoning_or_animal_attack_warning"])
        self.assertTrue(isolation["domain_opt_in_hard_gate"])
        self.assertTrue(isolation["profile_deny_only"])
        failure = SEMANTICS["failure_semantics"]
        self.assertTrue(all(failure.values()))
        self.assertGreaterEqual(len(SEMANTICS["invariants"]), 10)


if __name__ == "__main__":
    unittest.main()
