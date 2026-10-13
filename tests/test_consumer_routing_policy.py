"""Tests for provider-neutral Consumer routing semantics and profile policy."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "weather_router"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load_module(
    "weather_router_consumer_routing_policy",
    COMPONENT / "consumer_routing_policy.py",
)
profiles = load_module(
    "weather_router_consumer_profiles",
    COMPONENT / "consumer_profiles.py",
)
MAPPING = json.loads((COMPONENT / "consumer_capability_map.json").read_text(encoding="utf-8"))


class ConsumerRoutingPolicyTests(unittest.TestCase):
    def test_precipitation_intent_is_additive_and_has_five_raster_candidates(self) -> None:
        public_id = "weather.precipitation.layer"
        candidates = []
        for provider_id, provider_map in MAPPING["providers"].items():
            for internal_id, public_ids in provider_map.items():
                if public_id in public_ids:
                    candidates.append(f"{provider_id}/{internal_id}")
        self.assertEqual(
            set(candidates),
            {
                "dwd/radar_precipitation",
                "dwd/radar_precipitation_quality_checked",
                "rainviewer/radar_reflectivity",
                "nasa_gibs/satellite_precipitation_imerg_30min",
                "dwd/icon_eu_precipitation_1h",
            },
        )
        self.assertIn(
            "weather.radar.reflectivity",
            MAPPING["providers"]["rainviewer"]["radar_reflectivity"],
        )
        self.assertIn(
            "weather.radar.precipitation",
            MAPPING["providers"]["dwd"]["radar_precipitation"],
        )

    def test_shared_precipitation_intent_requires_machine_coverage(self) -> None:
        metadata = MAPPING["public_capabilities"]["weather.precipitation.layer"]
        self.assertEqual(metadata["coverage_policy"], "required")

    def test_precipitation_intent_contract_is_visual_not_numeric(self) -> None:
        metadata = MAPPING["public_capabilities"]["weather.precipitation.layer"]
        contract = metadata["intent_contract"]
        self.assertEqual(metadata["name"], "Niederschlag · beste verfügbare Flächenebene")
        self.assertEqual(contract["kind"], "visual_layer")
        self.assertEqual(contract["resource_type"], "raster_tile")
        self.assertTrue(contract["render_interchangeable"])
        self.assertFalse(contract["numeric_interchangeable"])
        self.assertEqual(contract["coverage"], "required")
        self.assertEqual(contract["attribution"], "required")
        self.assertEqual(contract["legend"], "required")
        self.assertEqual(contract["timeline"], "candidate_specific")
        self.assertEqual(contract["time_mode"], "latest")
        self.assertEqual(
            contract["semantic_fields"],
            [
                "data_origin",
                "measurement_method",
                "observation_kind",
                "quantity",
                "unit",
            ],
        )
        self.assertIn("uniform_quantity", contract["non_guarantees"])
        self.assertIn("uniform_unit", contract["non_guarantees"])
        self.assertIn("uniform_temporal_resolution", contract["non_guarantees"])

    def test_precipitation_intent_keeps_candidate_units_and_quantities_distinct(self) -> None:
        semantics = MAPPING["candidate_semantics"]
        keys = [
            "dwd/radar_precipitation_quality_checked",
            "rainviewer/radar_reflectivity",
            "dwd/radar_precipitation",
            "nasa_gibs/satellite_precipitation_imerg_30min",
            "dwd/icon_eu_precipitation_1h",
        ]
        quantities = {semantics[key]["quantity"] for key in keys}
        units = {semantics[key]["unit"] for key in keys}
        self.assertEqual(
            quantities,
            {
                "precipitation_rate",
                "radar_reflectivity",
                "precipitation_accumulation_1h",
            },
        )
        self.assertEqual(units, {None, "mm/h", "mm"})

    def test_physical_quantities_remain_distinct(self) -> None:
        semantics = MAPPING["candidate_semantics"]
        self.assertEqual(semantics["dwd/radar_precipitation"]["quantity"], "precipitation_rate")
        self.assertEqual(semantics["rainviewer/radar_reflectivity"]["quantity"], "radar_reflectivity")
        self.assertEqual(
            semantics["dwd/icon_eu_precipitation_1h"]["quantity"],
            "precipitation_accumulation_1h",
        )
        self.assertNotEqual(
            semantics["rainviewer/radar_reflectivity"]["measurement_method"],
            semantics["nasa_gibs/satellite_precipitation_imerg_30min"]["measurement_method"],
        )

    def test_scoring_uses_semantics_not_provider_id(self) -> None:
        radar = {
            "data_origin": "radar",
            "observation_kind": "observation",
            "quantity": "precipitation_rate",
        }
        same = dict(radar)
        self.assertEqual(
            policy.candidate_score(MAPPING, "weather.precipitation.layer", radar),
            policy.candidate_score(MAPPING, "weather.precipitation.layer", same),
        )
        satellite = {
            "data_origin": "satellite",
            "observation_kind": "estimate",
            "quantity": "precipitation_rate",
        }
        self.assertLess(
            policy.candidate_score(MAPPING, "weather.precipitation.layer", radar),
            policy.candidate_score(MAPPING, "weather.precipitation.layer", satellite),
        )

    def test_specialized_family_inference_is_provider_neutral(self) -> None:
        result = policy.normalized_candidate_semantics(
            MAPPING,
            "weather.nowcast.precipitation_rate",
            "example_provider",
            "example_capability",
            source_class="forecast",
            unit="mm/h",
        )
        self.assertEqual(result["data_origin"], "nowcast")
        self.assertEqual(result["observation_kind"], "nowcast")

    def test_profile_candidate_filters_are_deny_only(self) -> None:
        profile = {
            "name": "Gewitterradar",
            "enabled": True,
            "revision": 1,
            "excluded_data_origins": ["satellite"],
            "excluded_observation_kinds": ["forecast"],
            "excluded_providers": [],
        }
        allowed, reason = profiles.profile_allows_candidate(
            profile,
            {"data_origin": "radar", "measurement_method": "radar_reflectivity", "observation_kind": "observation"},
        )
        self.assertTrue(allowed)
        self.assertIsNone(reason)

        allowed, reason = profiles.profile_allows_candidate(
            profile,
            {"data_origin": "satellite", "measurement_method": "satellite_precipitation_estimate", "observation_kind": "estimate"},
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "profile_data_origin_filtered")

        allowed, reason = profiles.profile_allows_candidate(
            profile,
            {"data_origin": "model", "measurement_method": "nwp_precipitation_accumulation", "observation_kind": "forecast"},
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "profile_observation_kind_filtered")

    def test_p0_060_satellite_exclusion_is_deny_only(self) -> None:
        profile = {"excluded_data_origins": ["satellite"]}
        allowed, reason = profiles.profile_allows_candidate(
            profile,
            MAPPING["candidate_semantics"]["nasa_gibs/satellite_precipitation_imerg_30min"],
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "profile_data_origin_filtered")
        radar_allowed, radar_reason = profiles.profile_allows_candidate(
            profile,
            MAPPING["candidate_semantics"]["dwd/radar_precipitation_quality_checked"],
        )
        self.assertTrue(radar_allowed)
        self.assertIsNone(radar_reason)

    def test_p0_060_model_exclusion_is_deny_only(self) -> None:
        profile = {"excluded_data_origins": ["model"]}
        allowed, reason = profiles.profile_allows_candidate(
            profile,
            MAPPING["candidate_semantics"]["dwd/icon_eu_precipitation_1h"],
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "profile_data_origin_filtered")

    def test_p0_060_provider_exclusion_is_deny_only(self) -> None:
        profile = {"excluded_providers": ["dwd"]}
        self.assertFalse(profiles.profile_allows_provider(profile, "dwd"))
        self.assertTrue(profiles.profile_allows_provider(profile, "nasa_gibs"))

    def test_p0_060_reflectivity_exclusion_is_deny_only(self) -> None:
        profile = {"excluded_measurement_methods": ["radar_reflectivity"]}
        allowed, reason = profiles.profile_allows_candidate(
            profile,
            MAPPING["candidate_semantics"]["rainviewer/radar_reflectivity"],
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "profile_measurement_method_filtered")

    def test_p0_060_forecast_exclusion_is_deny_only(self) -> None:
        profile = {"excluded_observation_kinds": ["forecast"]}
        allowed, reason = profiles.profile_allows_candidate(
            profile,
            MAPPING["candidate_semantics"]["dwd/icon_eu_precipitation_1h"],
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "profile_observation_kind_filtered")
        estimate_allowed, estimate_reason = profiles.profile_allows_candidate(
            profile,
            MAPPING["candidate_semantics"]["nasa_gibs/satellite_precipitation_imerg_30min"],
        )
        self.assertTrue(estimate_allowed)
        self.assertIsNone(estimate_reason)

    def test_profile_normalization_accepts_candidate_exclusions_without_priority(self) -> None:
        normalized = profiles.normalize_consumer_profile(
            "gewitterradar",
            {
                "name": "Gewitterradar",
                "enabled": True,
                "excluded_providers": ["nasa_gibs"],
                "excluded_data_origins": ["satellite"],
                "excluded_measurement_methods": ["radar_reflectivity"],
                "excluded_observation_kinds": ["forecast"],
            },
            known_providers={"nasa_gibs"},
        )
        self.assertNotIn("preferred_providers", normalized)
        self.assertNotIn("provider_priority", normalized)
        self.assertEqual(normalized["excluded_data_origins"], ["satellite"])


    def test_machine_readable_audit_covers_full_baseline(self) -> None:
        audit = json.loads(
            (ROOT / "docs" / "consumer_routing_audit.v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(audit["schema"], "weather_router.consumer_routing_audit.v1")
        self.assertEqual(audit["baseline"]["core_provider_count"], 38)
        self.assertEqual(audit["baseline"]["public_capability_count"], 221)
        self.assertEqual(audit["post_precipitation_pilot"]["public_capability_count"], 222)
        self.assertEqual(len(audit["providers"]), 38)
        self.assertEqual(
            len(audit["public_capabilities"]),
            audit["runtime_mapping_sync"]["public_capability_count"],
        )
        self.assertEqual(audit["runtime_mapping_sync"]["public_capability_count"], 226)
        audited_ids = {row["public_capability"] for row in audit["public_capabilities"]}
        self.assertTrue(audited_ids.issubset(MAPPING["public_capabilities"]))
        self.assertLessEqual(
            audit["runtime_mapping_sync"]["public_capability_count"],
            len(MAPPING["public_capabilities"]),
        )
        self.assertFalse(audit["invariants"]["profile_provider_priority_allowed"])


if __name__ == "__main__":
    unittest.main()
