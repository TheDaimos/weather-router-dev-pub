"""Contract tests for the P3-WARN-40 runtime implementation."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "custom_components" / "weather_router" / "consumer_capability_map.json"
CONTRACT_PATH = ROOT / "contracts" / "consumer_v1" / "capability-map.draft.json"
HAZARD_HELPER_PATH = (
    ROOT / "custom_components" / "weather_router" / "providers" / "hazard_common.py"
)
DWD_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "dwd.py"
NWS_PATH = ROOT / "custom_components" / "weather_router" / "providers" / "noaa_nws.py"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"
CONSUMER_API_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
DIAGNOSTIC_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"


def _load_hazard_helper():
    spec = importlib.util.spec_from_file_location(
        "weather_router_hazard_common_test",
        HAZARD_HELPER_PATH,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load hazard_common.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class P3WarnImplementationTest(unittest.TestCase):
    """Protect the P3-WARN-40 spatial warning implementation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.helper = _load_hazard_helper()
        cls.dwd_source = DWD_PATH.read_text(encoding="utf-8")
        cls.nws_source = NWS_PATH.read_text(encoding="utf-8")
        cls.const_source = CONST_PATH.read_text(encoding="utf-8")
        cls.consumer_source = CONSUMER_API_PATH.read_text(encoding="utf-8")
        cls.diagnostic_source = DIAGNOSTIC_PATH.read_text(encoding="utf-8")

    def _candidates(self, public_id: str) -> list[str]:
        result: list[str] = []
        for provider_id, capabilities in self.mapping["providers"].items():
            for capability_id, public_ids in capabilities.items():
                if public_id in public_ids:
                    result.append(f"{provider_id}/{capability_id}")
        return result

    def test_runtime_and_contract_maps_stay_identical(self) -> None:
        self.assertEqual(self.mapping, self.contract)

    def test_warning_public_contract_remains_existing_aggregate(self) -> None:
        self.assertGreaterEqual(len(self.mapping["public_capabilities"]), 226)
        meta = self.mapping["public_capabilities"]["weather.warning.official"]
        self.assertEqual(meta["strategy"], "aggregate")
        self.assertIn("hazard_feed", meta["resource_types"])
        self.assertEqual(
            self._candidates("weather.warning.official"),
            [
                "dwd/official_weather_warnings",
                "noaa_nws/official_weather_alerts",
            ],
        )

    def test_dwd_uses_official_cap_status_product_with_polygons(self) -> None:
        for marker in (
            "COMMUNEUNION_CELLS_STAT",
            "Z_CAP_C_EDZW_LATEST_PVW_STATUS_PREMIUMCELLS_COMMUNEUNION_DE.zip",
            "_parse_dwd_cap_zip",
            "_parse_cap_ring",
            "_cap_geometry_and_areas",
            '"type": "Polygon"',
            '"type": "MultiPolygon"',
            "WARNCELLID",
            "EXCLUDE_POLYGON",
            "opendata.dwd.de",
        ):
            self.assertIn(marker, self.dwd_source)
        self.assertNotIn("warnWetter.loadWarnings(", self.dwd_source)
        self.assertNotIn("_DWD_WARNINGS_URL", self.dwd_source)

    def test_dwd_zip_parsing_is_offloaded_from_event_loop(self) -> None:
        self.assertIn(
            "await hass.async_add_executor_job(_parse_dwd_cap_zip, raw_payload)",
            self.dwd_source,
        )
        self.assertIn("25 * 1024 * 1024", self.dwd_source)
        self.assertIn("contains too many members", self.dwd_source)

    def test_dwd_point_and_bbox_filter_fail_closed_without_geometry(self) -> None:
        self.assertIn("point_in_geometry(", self.dwd_source)
        self.assertIn("geometry_intersects_bbox_strict(", self.dwd_source)
        self.assertIn("excluded_missing_geometry", self.dwd_source)
        self.assertIn('"event_relevance_evidence": (', self.dwd_source)
        self.assertIn('"runtime_event_geometry"', self.dwd_source)
        self.assertIn('"authority_coverage_status": (', self.dwd_source)
        self.assertIn('"no_active_matching_warning_not_outside_coverage"', self.dwd_source)

    def test_nws_bbox_path_uses_strict_geometry_evidence(self) -> None:
        self.assertIn("geometry_intersects_bbox_strict", self.nws_source)
        self.assertNotIn("geometry_intersects_bbox(", self.nws_source)
        self.assertIn('"authority_coverage_status": (', self.nws_source)
        self.assertIn('"no_active_matching_warning_not_outside_coverage"', self.nws_source)

    def test_strict_bbox_missing_geometry_is_false(self) -> None:
        bbox = (9.0, 53.0, 10.0, 54.0)
        self.assertFalse(self.helper.geometry_intersects_bbox_strict(None, bbox))
        self.assertFalse(
            self.helper.geometry_intersects_bbox_strict(
                {"type": "Polygon", "coordinates": None},
                bbox,
            )
        )

    def test_point_in_polygon_and_hole_semantics(self) -> None:
        geometry = {
            "type": "Polygon",
            "coordinates": [
                [
                    [9.0, 53.0],
                    [10.0, 53.0],
                    [10.0, 54.0],
                    [9.0, 54.0],
                    [9.0, 53.0],
                ],
                [
                    [9.4, 53.4],
                    [9.6, 53.4],
                    [9.6, 53.6],
                    [9.4, 53.6],
                    [9.4, 53.4],
                ],
            ],
        }
        self.assertTrue(self.helper.point_in_geometry(geometry, 9.2, 53.2))
        self.assertFalse(self.helper.point_in_geometry(geometry, 9.5, 53.5))
        self.assertFalse(self.helper.point_in_geometry(geometry, 11.0, 53.5))

    def test_bbox_intersection_detects_containment_and_edge_crossing(self) -> None:
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [9.0, 53.0],
                [11.0, 53.0],
                [11.0, 55.0],
                [9.0, 55.0],
                [9.0, 53.0],
            ]],
        }
        self.assertTrue(
            self.helper.geometry_intersects_bbox_strict(
                geometry,
                (9.5, 53.5, 10.0, 54.0),
            )
        )
        self.assertTrue(
            self.helper.geometry_intersects_bbox_strict(
                geometry,
                (10.5, 54.5, 12.0, 56.0),
            )
        )
        self.assertFalse(
            self.helper.geometry_intersects_bbox_strict(
                geometry,
                (12.0, 56.0, 13.0, 57.0),
            )
        )

    def test_global_backward_compatible_helper_stays_conservative(self) -> None:
        bbox = (9.0, 53.0, 10.0, 54.0)
        self.assertTrue(self.helper.geometry_intersects_bbox(None, bbox))

    def test_warning_spatial_evidence_reaches_routing_diagnostics(self) -> None:
        self.assertIn('"source_diagnostics": source_diagnostics', self.consumer_source)
        self.assertIn('"spatial_filter": payload.get("spatial_filter")', self.consumer_source)
        self.assertIn('"geometry_status": payload.get("geometry_status")', self.consumer_source)
        self.assertIn('"source_diagnostics"', self.diagnostic_source)

    def test_zero_spatial_matches_are_not_mislabeled_outside_coverage(self) -> None:
        for source in (self.dwd_source, self.nws_source):
            self.assertIn('"context_match"', source)
            self.assertIn('"unknown"', source)
            self.assertIn("no_active_matching_warning_not_outside_coverage", source)

    def test_build_and_loader_are_not_older_than_warning_runtime(self) -> None:
        build_match = re.search(
            r'DEV_BUILD_VERSION: Final = "(\d+)\.(\d+)\.(\d+)"',
            self.const_source,
        )
        loader_match = re.search(
            r'DEV_LOADER_REV: Final = "0\.10-loader-(\d+)"',
            self.const_source,
        )
        self.assertIsNotNone(build_match)
        self.assertIsNotNone(loader_match)
        assert build_match is not None
        assert loader_match is not None
        build = tuple(int(item) for item in build_match.groups())
        loader = int(loader_match.group(1))
        self.assertGreaterEqual(build, (0, 10, 120))
        self.assertGreaterEqual(loader, 123)

    def test_no_provider_priority_or_dedup_contract_is_added(self) -> None:
        raw = MAP_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("preferred_provider", raw)
        self.assertNotIn("provider_priority", raw)


if __name__ == "__main__":
    unittest.main()
