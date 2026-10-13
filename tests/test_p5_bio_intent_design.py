"""Static contract audit for P5-BIO-30 design. No GBIF network I/O."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


DESIGN = load("docs/p5_bio_intent_design.v1.json")
SEMANTICS = load("docs/p5_bio_semantics.v1.json")
INVENTORY = load("docs/p5_bio_inventory.v1.json")
MAPPING = load("custom_components/weather_router/consumer_capability_map.json")
REGISTRY = load("custom_components/weather_router/providers/registry.json")["providers"]
SOURCE = (
    ROOT / "custom_components/weather_router/providers/gbif_biodiversity.py"
).read_text(encoding="utf-8")
CONSUMER = (
    ROOT / "custom_components/weather_router/consumer_api.py"
).read_text(encoding="utf-8")


class P5BioIntentDesignTest(unittest.TestCase):
    def test_scope_preserves_88_existing_single_rasters(self):
        self.assertEqual(DESIGN["schema"], "weather_router.p5_bio_intent_design.v1")
        target = DESIGN["baseline"]
        self.assertEqual(target["public_capability_count"], 227)
        self.assertEqual(target["biological_public_capability_count"], 88)
        self.assertEqual(len(MAPPING["public_capabilities"]), 227)
        contract = DESIGN["public_contract"]
        self.assertEqual(contract["family"], "biological_occurrence_density")
        self.assertEqual(contract["strategy"], "single")
        self.assertEqual(contract["resource_type"], "raster_tile")
        self.assertEqual(contract["new_public_capability_count"], 0)
        self.assertFalse(contract["new_shared_intent"])
        self.assertEqual(len(INVENTORY["taxa"]), 88)
        for item in INVENTORY["taxa"]:
            self.assertEqual(
                MAPPING["providers"]["gbif_biodiversity"][item["capability_id"]],
                [item["public_id"]],
            )

    def test_context_is_map_only_not_local_presence(self):
        context = DESIGN["context_contract"]
        self.assertEqual(context["global"], "map_layer_allowed")
        self.assertEqual(context["bbox"], "same_map_layer_no_server_filter")
        self.assertEqual(context["point"], "same_map_layer_no_point_sample")
        self.assertEqual(context["nearby"], "no_implicit_radius_or_local_risk")
        self.assertEqual(context["risk_estimation"], "not_supported")
        self.assertIn('return ["global", "point", "bbox"]', CONSUMER)
        method = SOURCE.split("async def async_get_map_layer(", 1)[1].split(
            "async def async_get_taxon_layer(", 1
        )[0]
        self.assertNotIn("latitude", method)
        self.assertNotIn("longitude", method)

    def test_coverage_cannot_be_converted_to_global_presence(self):
        coverage = DESIGN["spatial_coverage"]
        sem = SEMANTICS["coverage"]
        for key in (
            "coverage_scope", "coverage_evidence", "routing_authority",
            "coordinate_space", "endpoint_reachability_is_coverage",
        ):
            self.assertEqual(coverage[key], sem[key])
        self.assertEqual(coverage["coverage_scope"], "unknown")
        self.assertFalse(coverage["endpoint_reachability_is_coverage"])

    def test_opt_in_and_dynamic_admin_query_are_kept_separate(self):
        contract = DESIGN["public_contract"]
        self.assertFalse(contract["default_enabled"])
        self.assertEqual(contract["provider"], "gbif_biodiversity")
        rows = [x for x in REGISTRY if x["class"] == "GbifBiodiversityProvider"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["default_enabled"])
        self.assertTrue(DESIGN["behavior"]["keep_existing_domain_opt_in"])
        self.assertTrue(DESIGN["behavior"]["keep_deny_only_profiles"])
        self.assertTrue(DESIGN["behavior"]["keep_admin_dynamic_taxon_nonpublic"])
        self.assertNotIn("dynamic_taxon_search", MAPPING["providers"]["gbif_biodiversity"])

    def test_required_resource_and_metadata_are_provided(self):
        details = DESIGN["provider_resource"]
        self.assertEqual(details["method"], "async_get_map_layer")
        self.assertEqual(details["result_resource_type"], "raster_tile")
        for name in details["required_fields"]:
            self.assertIn('"' + name + '":', SOURCE)
        for name in details["provenance_keys"]:
            self.assertIn('"' + name + '":', SOURCE)
        self.assertIn('"hasGeospatialIssue": "false"', SOURCE)
        self.assertTrue(details["tile_template_is_not_download_proof"])
        self.assertTrue(DESIGN["behavior"]["provenance_required"])
        self.assertTrue(DESIGN["behavior"]["temporal_warning_required"])

    def test_safe_future_stage_boundaries_are_enforced(self):
        behavior = DESIGN["behavior"]
        for key in (
            "no_new_provider_or_public_ids", "no_generated_hazard_feed",
            "no_population_or_risk_estimator", "no_taxon_group_aggregation",
            "no_inferred_global_coverage",
        ):
            self.assertTrue(behavior[key])
        self.assertEqual(DESIGN["implementation_plan"]["phase"], "P5-BIO-40")
        self.assertTrue(
            DESIGN["implementation_plan"]["runtime_version_bump_required_only_if_runtime_changes"]
        )
        self.assertEqual(DESIGN["static_acceptance"]["phase"], "P5-BIO-50")
        self.assertEqual(DESIGN["ha_test_plan"]["phase"], "P5-BIO-60")
        self.assertEqual(len(DESIGN["ha_test_plan"]["mandatory_test_names"]), 6)
        self.assertGreaterEqual(len(DESIGN["invariants"]), 8)


if __name__ == "__main__":
    unittest.main()
