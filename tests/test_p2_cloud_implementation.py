"""Static runtime contract tests for P2-CLOUD-40 implementation."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "weather_router"
MAP_PATH = COMPONENT / "consumer_capability_map.json"
EUMETVIEW_PATH = COMPONENT / "providers" / "eumetview.py"


class P2CloudImplementationTest(unittest.TestCase):
    """Guard the implemented shared cloud contracts and specialized paths."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    def _candidates(self, public_id: str) -> set[str]:
        result: set[str] = set()
        for provider_id, provider_map in self.mapping["providers"].items():
            for internal_id, public_ids in provider_map.items():
                if public_id in public_ids:
                    result.add(f"{provider_id}/{internal_id}")
        return result

    def test_public_capability_count_includes_cloud_observation_path(self) -> None:
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        self.assertIn(
            "weather.observation.cloud_cover",
            self.mapping["public_capabilities"],
        )

    def test_total_cloud_forecast_candidate_set_excludes_eccc(self) -> None:
        self.assertEqual(
            self._candidates("weather.point.cloud_cover"),
            {
                "open_meteo/cloud_cover",
                "met_norway/cloud_cover",
                "fmi/cloud_cover",
                "smhi/cloud_cover",
            },
        )
        self.assertNotIn(
            "eccc_geomet/cloud_cover",
            self._candidates("weather.point.cloud_cover"),
        )

    def test_vertical_forecast_candidate_sets_are_stable(self) -> None:
        self.assertEqual(
            self._candidates("weather.point.cloud_cover_low"),
            {
                "open_meteo/cloud_cover_low",
                "met_norway/cloud_cover_low",
                "smhi/cloud_cover_low",
            },
        )
        self.assertEqual(
            self._candidates("weather.point.cloud_cover_mid"),
            {
                "open_meteo/cloud_cover_mid",
                "met_norway/cloud_cover_mid",
                "smhi/cloud_cover_mid",
            },
        )
        self.assertEqual(
            self._candidates("weather.point.cloud_cover_high"),
            {
                "open_meteo/cloud_cover_high",
                "met_norway/cloud_cover_high",
                "smhi/cloud_cover_high",
            },
        )

    def test_eccc_is_exposed_only_as_specialized_observation(self) -> None:
        self.assertEqual(
            self._candidates("weather.observation.cloud_cover"),
            {"eccc_geomet/cloud_cover"},
        )
        contract = self.mapping["public_capabilities"][
            "weather.observation.cloud_cover"
        ]["intent_contract"]
        self.assertEqual(contract["observation_kind_policy"], "observation")
        self.assertEqual(
            contract["quantity_policy"],
            "total_cloud_amount_observed",
        )
        self.assertIsNone(contract["canonical_unit"])
        self.assertEqual(
            contract["unit_policy"],
            "candidate_specific_runtime",
        )

    def test_cloud_quantities_are_refined_by_vertical_layer(self) -> None:
        physical = self.mapping["capability_physical_semantics"]["providers"]
        expected = {
            "cloud_cover": "cloud_cover_fraction_total",
            "cloud_cover_low": "cloud_cover_fraction_low",
            "cloud_cover_mid": "cloud_cover_fraction_mid",
            "cloud_cover_high": "cloud_cover_fraction_high",
        }
        for provider_id in ("open_meteo", "met_norway", "smhi"):
            for capability_id, quantity in expected.items():
                self.assertEqual(
                    physical[provider_id][capability_id]["quantity"],
                    quantity,
                )
        self.assertEqual(
            physical["fmi"]["cloud_cover"]["quantity"],
            "cloud_cover_fraction_total",
        )
        self.assertEqual(
            physical["eccc_geomet"]["cloud_cover"]["quantity"],
            "total_cloud_amount_observed",
        )

    def test_point_intent_contracts_are_forecast_percent(self) -> None:
        public = self.mapping["public_capabilities"]
        expected = {
            "weather.point.cloud_cover": "cloud_cover_fraction_total",
            "weather.point.cloud_cover_low": "cloud_cover_fraction_low",
            "weather.point.cloud_cover_mid": "cloud_cover_fraction_mid",
            "weather.point.cloud_cover_high": "cloud_cover_fraction_high",
        }
        for public_id, quantity in expected.items():
            contract = public[public_id]["intent_contract"]
            self.assertEqual(contract["resource_type"], "value")
            self.assertTrue(contract["numeric_interchangeable"])
            self.assertEqual(contract["quantity_policy"], quantity)
            self.assertEqual(contract["canonical_unit"], "%")
            self.assertEqual(contract["observation_kind_policy"], "forecast")

    def test_satellite_cloud_shared_intent_is_visual_and_coverage_gated(self) -> None:
        self.assertEqual(
            self._candidates("weather.satellite.clouds"),
            {"dwd/satellite_clouds", "eumetview/satellite_clouds"},
        )
        metadata = self.mapping["public_capabilities"]["weather.satellite.clouds"]
        contract = metadata["intent_contract"]
        self.assertEqual(metadata["coverage_policy"], "required")
        self.assertEqual(contract["kind"], "visual_layer")
        self.assertEqual(contract["resource_type"], "raster_tile")
        self.assertTrue(contract["render_interchangeable"])
        self.assertFalse(contract["numeric_interchangeable"])
        self.assertEqual(contract["coverage"], "required")
        self.assertEqual(contract["attribution"], "required")

    def test_eumetview_declares_hard_machine_coverage_and_provider_supports_it(self) -> None:
        coverage = self.mapping["capability_coverage_semantics"]["providers"][
            "eumetview"
        ]["satellite_clouds"]
        self.assertEqual(coverage["coverage_scope"], "bbox")
        self.assertEqual(
            coverage["coverage_evidence"],
            "machine_readable_runtime",
        )
        self.assertEqual(coverage["routing_authority"], "hard")
        self.assertFalse(coverage["endpoint_reachability_is_coverage"])

        source = EUMETVIEW_PATH.read_text(encoding="utf-8")
        self.assertIn("async def async_get_coverage(", source)
        self.assertIn("wms_layer_geographic_coverage", source)
        self.assertIn("EUMETView WMS GetCapabilities", source)

    def test_nasa_specialized_product_paths_are_not_folded_into_cloud_layer(self) -> None:
        cloud_candidates = self._candidates("weather.satellite.clouds")
        self.assertFalse(any(item.startswith("nasa_gibs/") for item in cloud_candidates))
        specialized = {
            "weather.satellite.true_color",
            "weather.satellite.geocolor.goes_east",
            "weather.satellite.geocolor.goes_west",
            "weather.satellite.infrared.goes_east",
            "weather.satellite.infrared.goes_west",
            "weather.satellite.infrared.himawari_9",
            "weather.satellite.visible_red.goes_east",
            "weather.satellite.visible_red.goes_west",
            "weather.satellite.visible_red.himawari_9",
            "weather.satellite.air_mass.goes_east",
            "weather.satellite.air_mass.goes_west",
            "weather.satellite.air_mass.himawari_9",
        }
        self.assertTrue(specialized.issubset(self.mapping["public_capabilities"]))

    def test_cloud_contract_does_not_add_provider_priority(self) -> None:
        raw = MAP_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn('"preferred_providers"', raw)
        self.assertNotIn('"provider_priority"', raw)


if __name__ == "__main__":
    unittest.main()
