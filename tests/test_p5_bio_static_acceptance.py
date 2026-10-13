"""Independent static acceptance of P5-BIO-50.

Contract, provider, runtime and safety checks run without GBIF network traffic.
This file does not import or depend on the earlier P5-BIO stage tests.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "custom_components/weather_router"
MAPPING = json.loads((SRC / "consumer_capability_map.json").read_text(encoding="utf-8"))
TAXA = json.loads((SRC / "providers/biological_taxa.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((SRC / "providers/registry.json").read_text(encoding="utf-8"))
API = (SRC / "consumer_api.py").read_text(encoding="utf-8")
PROVIDER = (SRC / "providers/gbif_biodiversity.py").read_text(encoding="utf-8")
CONST = (SRC / "const.py").read_text(encoding="utf-8")
LAB = (SRC / "frontend/weather-router-lab.js").read_text(encoding="utf-8")
LOADER = (SRC / "frontend/weather-router-lab-dev-loader.js").read_text(encoding="utf-8")
DESIGN = json.loads((ROOT / "docs/p5_bio_intent_design.v1.json").read_text(encoding="utf-8"))
SEMANTICS = json.loads((ROOT / "docs/p5_bio_semantics.v1.json").read_text(encoding="utf-8"))


from wr_public_version_contract import assert_current_version_surfaces

class P5BioStaticAcceptance(unittest.TestCase):
    def test_01_public_count_stays_227_and_biological_88(self):
        public = MAPPING["public_capabilities"]
        self.assertEqual(len(public), 227)
        self.assertEqual(
            len([k for k in public if k.startswith("biological_hazards.")]), 88
        )

    def test_02_provider_opt_in_and_correct_domain(self):
        providers = [p for p in REGISTRY["providers"] if p["class"] == "GbifBiodiversityProvider"]
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["module"], "gbif_biodiversity")
        self.assertEqual(providers[0]["domains"], ["biological_hazards"])
        self.assertFalse(providers[0]["default_enabled"])
        self.assertIn('"biological_hazards": "Biologische Gefahren & Wildtiere"', CONST)

    def test_03_all_88_taxa_have_one_exact_internal_public_pair(self):
        self.assertEqual(len(TAXA["taxa"]), 88)
        provider_map = MAPPING["providers"]["gbif_biodiversity"]
        self.assertEqual(len(provider_map), 88)
        for taxon in TAXA["taxa"]:
            internal = "occurrence_density_" + taxon["id"]
            public_id = "biological_hazards.occurrence." + taxon["id"] + ".density"
            self.assertEqual(provider_map[internal], [public_id])

    def test_04_all_public_contracts_specialized_single_raster(self):
        public = MAPPING["public_capabilities"]
        for k, v in public.items():
            if not k.startswith("biological_hazards."):
                continue
            self.assertEqual(v["family"], "biological_occurrence_density")
            self.assertEqual(v["strategy"], "single")
            self.assertEqual(v["resource_types"], ["raster_tile"])
        self.assertFalse(DESIGN["public_contract"]["new_shared_intent"])

    def test_05_physics_are_observations_not_risk_scores(self):
        details = MAPPING["capability_physical_semantics"]["providers"]["gbif_biodiversity"]
        source = MAPPING["capability_source_semantics"]["providers"]["gbif_biodiversity"]
        obs = MAPPING["capability_observation_semantics"]["providers"]["gbif_biodiversity"]
        self.assertEqual(len(details), 88)
        for k, v in details.items():
            self.assertTrue(v["numeric"])
            self.assertEqual(v["quantity"], "occurrence_density")
            self.assertEqual(source[k]["data_origin"], "biodiversity_observation")
            self.assertEqual(source[k]["measurement_method"], "occurrence_density_observation")
            self.assertEqual(obs[k]["observation_kind"], "observation")
        self.assertIs(SEMANTICS["physical_semantics"]["hazard_probability"], False)
        self.assertIs(SEMANTICS["physical_semantics"]["current_presence"], False)

    def test_06_spatial_coverage_is_unknown_not_global_guarantee(self):
        coverage = MAPPING["capability_coverage_semantics"]["providers"]["gbif_biodiversity"]
        self.assertEqual(len(coverage), 88)
        for row in coverage.values():
            self.assertEqual(row["coverage_scope"], "unknown")
            self.assertEqual(row["coverage_evidence"], "unknown")
            self.assertEqual(row["routing_authority"], "none")
            self.assertFalse(row["endpoint_reachability_is_coverage"])

    def test_07_time_is_not_nowcast(self):
        timeline = MAPPING["capability_time_semantics"]["providers"]["gbif_biodiversity"]
        for row in timeline.values():
            self.assertEqual(row["request_time_mode"], "latest")
            self.assertEqual(row["valid_time"], "not_applicable")
            self.assertEqual(row["forecast_reference_time"], "not_applicable")
        self.assertIn('"year": f"{from_year},{current_year}"', PROVIDER)

    def test_08_three_contexts_are_map_requests_not_local_presence(self):
        self.assertIn('if render_mode == "raster_tile":', API)
        self.assertIn('return ["global", "point", "bbox"]', API)
        self.assertIn('result = await fetch(hass, candidate.capability.id)', API)
        method = PROVIDER.split("async def async_get_map_layer(", 1)[1].split(
            "async def async_get_taxon_layer(", 1
        )[0]
        self.assertNotIn("latitude", method)
        self.assertNotIn("longitude", method)
        self.assertEqual(SEMANTICS["context_contract"]["bbox"], "allowed_as_map_viewport_not_server_side_bbox_filter")

    def test_09_admin_dynamic_taxon_is_not_a_public_capability(self):
        self.assertIn("async_get_taxon_layer", PROVIDER)
        self.assertNotIn("dynamic_taxon_search", MAPPING["providers"]["gbif_biodiversity"])

    def test_10_public_gbif_provenance_is_safely_preserved(self):
        self.assertIn('if result.get("provider") == "gbif_biodiversity":', API)
        self.assertIn('payload["provider_metadata"] = public_metadata', API)
        self.assertIn('_safe_public_url(raw_metadata.get("data_user_agreement"))', API)
        for field in (
            "scientific_name_requested", "scientific_name_matched", "taxon_key",
            "taxon_rank", "taxon_status", "match_confidence",
            "from_year", "to_year", "population_density", "risk_probability",
            "warning", "data_user_agreement",
        ):
            self.assertIn('"' + field + '"', API)
        self.assertIn('"population_density": False', PROVIDER)
        self.assertIn('"risk_probability": False', PROVIDER)

    def test_11_no_unfiltered_upstream_provider_metadata(self):
        self.assertNotIn('payload["provider_metadata"] = raw_metadata', API)
        self.assertIn('string_fields = (', API)
        self.assertIn('for field in string_fields:', API)
        self.assertNotIn('payload.update(result.get("provider_metadata")', API)

    def test_12_attribution_licence_and_warnings_are_present(self):
        self.assertIn("GBIF.org", PROVIDER)
        self.assertIn("underlying dataset licences apply", PROVIDER)
        self.assertIn("_TERMS_URL", PROVIDER)
        self.assertIn('"warning": (', PROVIDER)
        self.assertTrue(SEMANTICS["map_provenance"]["attribution_required"])

    def test_13_biological_hazards_never_become_an_official_warning(self):
        self.assertFalse(SEMANTICS["physical_semantics"]["official_hazard_warning"])
        self.assertTrue(SEMANTICS["isolation"]["no_weather_hazard_or_civil_warning_fallback"])
        self.assertTrue(SEMANTICS["isolation"]["no_auto_disease_outbreak_inference"])
        self.assertFalse(SEMANTICS["taxon_semantics"]["additive_species_and_parent_group_counts"])

    def test_14_no_runtime_network_access_is_triggered_by_this_test(self):
        # Only the static source and local JSON contracts are referenced.
        self.assertEqual(SRC.parts[-2:], ("custom_components", "weather_router"))
        self.assertTrue(SRC.is_dir(), "Quellverzeichnis fehlt")
        self.assertEqual(DESIGN["implementation_plan"]["phase"], "P5-BIO-40")
        self.assertEqual(DESIGN["ha_test_plan"]["phase"], "P5-BIO-60")
        self.assertEqual(len(DESIGN["ha_test_plan"]["mandatory_test_names"]), 6)

    def test_15_build_lab_loader_are_exactly_synchronized(self):
        assert_current_version_surfaces(self, CONST, LAB, LOADER)


if __name__ == "__main__":
    unittest.main()
