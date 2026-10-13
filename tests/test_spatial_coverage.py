"""Unit tests for provider-neutral raster coverage routing."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "weather_router" / "spatial_coverage.py"
SPEC = importlib.util.spec_from_file_location("weather_router_spatial_coverage", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)


class RasterCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dwd_like = {
            "scope": "bbox",
            "bbox": {"west": 2.0, "south": 46.0, "east": 17.0, "north": 56.0},
            "source": "wms_get_capabilities",
            "layer": "Niederschlagsradar",
        }

    def test_a_dwd_precipitation_germany_ready(self) -> None:
        context = {"type": "bbox", "west": 7.0, "south": 49.0, "east": 12.0, "north": 54.0}
        self.assertTrue(coverage.coverage_matches_context(self.dwd_like, context))

    def test_b_dwd_precipitation_puntland_rejected(self) -> None:
        context = {"type": "bbox", "west": 47.0, "south": 7.0, "east": 52.0, "north": 12.0}
        self.assertFalse(coverage.coverage_matches_context(self.dwd_like, context))

    def test_c_no_other_provider_means_no_spatial_match(self) -> None:
        context = {"type": "bbox", "west": 47.0, "south": 7.0, "east": 52.0, "north": 12.0}
        matches = [
            item
            for item in (self.dwd_like,)
            if coverage.coverage_matches_context(item, context)
        ]
        self.assertEqual(matches, [])

    def test_d_resolver_can_fall_back_to_next_coverage(self) -> None:
        context = {"type": "bbox", "west": 47.0, "south": 7.0, "east": 52.0, "north": 12.0}
        later_global_provider = {"scope": "global", "source": "provider_metadata"}
        matches = [
            index
            for index, item in enumerate((self.dwd_like, later_global_provider))
            if coverage.coverage_matches_context(item, context)
        ]
        self.assertEqual(matches[0], 1)

    def test_d2_global_coverage_accepts_open_atlantic_bbox(self) -> None:
        global_coverage = {"scope": "global", "source": "wms_get_capabilities"}
        context = {
            "type": "bbox",
            "west": -38.1,
            "south": 16.6,
            "east": -26.9,
            "north": 23.3,
        }
        self.assertTrue(coverage.coverage_matches_context(global_coverage, context))

    def test_e_bbox_fully_inside(self) -> None:
        inside = {"type": "bbox", "west": 8.0, "south": 48.0, "east": 14.0, "north": 55.0}
        self.assertTrue(coverage.coverage_matches_context(self.dwd_like, inside))

    def test_f_bbox_partially_overlapping(self) -> None:
        partial = {"type": "bbox", "west": 16.0, "south": 50.0, "east": 20.0, "north": 54.0}
        self.assertTrue(coverage.coverage_matches_context(self.dwd_like, partial))

    def test_g_bbox_fully_outside(self) -> None:
        outside = {"type": "bbox", "west": -80.0, "south": 25.0, "east": -70.0, "north": 35.0}
        self.assertFalse(coverage.coverage_matches_context(self.dwd_like, outside))

    def test_h_antimeridian_bbox(self) -> None:
        pacific = {
            "scope": "bbox",
            "bbox": {"west": 175.0, "south": -20.0, "east": -175.0, "north": 20.0},
        }
        request = {"type": "bbox", "west": 170.0, "south": -5.0, "east": -170.0, "north": 5.0}
        self.assertTrue(coverage.coverage_matches_context(pacific, request))
        self.assertFalse(coverage.coverage_matches_context(self.dwd_like, request))

    def test_i_global_context_rejects_regional_provider(self) -> None:
        self.assertFalse(
            coverage.coverage_matches_context(self.dwd_like, {"type": "global"})
        )

    def test_j_existing_germany_point_context(self) -> None:
        point = {"type": "point", "latitude": 53.55, "longitude": 9.99}
        self.assertTrue(coverage.coverage_matches_context(self.dwd_like, point))

    def test_wms_concrete_layer_ex_geographic_bbox(self) -> None:
        root = ET.fromstring(
            """<WMS_Capabilities xmlns="http://www.opengis.net/wms">
            <Capability><Layer><Layer><Name>Niederschlagsradar</Name>
            <EX_GeographicBoundingBox>
              <westBoundLongitude>2</westBoundLongitude>
              <eastBoundLongitude>17</eastBoundLongitude>
              <southBoundLatitude>46</southBoundLatitude>
              <northBoundLatitude>56</northBoundLatitude>
            </EX_GeographicBoundingBox>
            </Layer></Layer></Capability></WMS_Capabilities>"""
        )
        parsed = coverage.wms_layer_geographic_coverage(root, "Niederschlagsradar")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(
            parsed["bbox"],
            {"west": 2.0, "south": 46.0, "east": 17.0, "north": 56.0},
        )

    def test_bbox_diagnostic_partial_overlap_is_explanatory_only(self) -> None:
        request = {"type": "bbox", "west": 16.0, "south": 50.0, "east": 20.0, "north": 54.0}
        diagnostic = coverage.coverage_diagnostics(self.dwd_like, request)
        self.assertTrue(diagnostic["routing_match"])
        self.assertTrue(diagnostic["bbox_intersects"])
        self.assertGreater(diagnostic["overlap_percent"], 0.0)
        self.assertLess(diagnostic["overlap_percent"], 100.0)
        self.assertFalse(diagnostic["consumer_fully_inside"])

    def test_bbox_diagnostic_antimeridian_center_and_width(self) -> None:
        context = {"type": "bbox", "west": 170.0, "south": -10.0, "east": -170.0, "north": 10.0}
        diagnostic = coverage.context_diagnostics(context)
        self.assertTrue(diagnostic["crosses_antimeridian"])
        self.assertEqual(diagnostic["longitude_width_deg"], 20.0)
        self.assertIn(abs(diagnostic["center"]["longitude"]), (180.0,))

    def test_wms_inherits_bbox_from_real_parent_layer_group(self) -> None:
        root = ET.fromstring(
            """<WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0">
            <Capability><Layer>
              <EX_GeographicBoundingBox>
                <westBoundLongitude>-180</westBoundLongitude>
                <eastBoundLongitude>180</eastBoundLongitude>
                <southBoundLatitude>-90</southBoundLatitude>
                <northBoundLatitude>90</northBoundLatitude>
              </EX_GeographicBoundingBox>
              <Layer><Name>Kurzfristvorhersagen</Name>
                <EX_GeographicBoundingBox>
                  <westBoundLongitude>-75</westBoundLongitude>
                  <eastBoundLongitude>75</eastBoundLongitude>
                  <southBoundLatitude>-80</southBoundLatitude>
                  <northBoundLatitude>80</northBoundLatitude>
                </EX_GeographicBoundingBox>
                <Layer><Name>dwd:Icon_reg025_fd_sl_T2M</Name></Layer>
              </Layer>
            </Layer></Capability></WMS_Capabilities>"""
        )
        parsed = coverage.wms_layer_geographic_coverage(
            root, "Icon_reg025_fd_sl_T2M"
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(
            parsed["bbox"],
            {"west": -75.0, "south": -80.0, "east": 75.0, "north": 80.0},
        )
        self.assertTrue(parsed["bbox_inherited"])
        self.assertEqual(parsed["bbox_inherited_from"], "Kurzfristvorhersagen")

    def test_wms_does_not_treat_parent_world_bbox_as_layer_coverage(self) -> None:
        root = ET.fromstring(
            """<WMS_Capabilities xmlns="http://www.opengis.net/wms">
            <Capability><Layer>
            <EX_GeographicBoundingBox>
              <westBoundLongitude>-180</westBoundLongitude>
              <eastBoundLongitude>180</eastBoundLongitude>
              <southBoundLatitude>-90</southBoundLatitude>
              <northBoundLatitude>90</northBoundLatitude>
            </EX_GeographicBoundingBox>
            <Layer><Name>Niederschlagsradar</Name></Layer>
            </Layer></Capability></WMS_Capabilities>"""
        )
        self.assertIsNone(
            coverage.wms_layer_geographic_coverage(root, "Niederschlagsradar")
        )

    def test_diagnostics_never_change_routing_semantics(self) -> None:
        contexts = (
            {"type": "bbox", "west": 7.0, "south": 49.0, "east": 12.0, "north": 54.0},
            {"type": "bbox", "west": 47.0, "south": 7.0, "east": 52.0, "north": 12.0},
            {"type": "point", "latitude": 53.55, "longitude": 9.99},
            {"type": "point", "latitude": 10.0, "longitude": 50.0},
            {"type": "global"},
        )
        for context in contexts:
            with self.subTest(context=context):
                expected = coverage.coverage_matches_context(self.dwd_like, context)
                diagnostic = coverage.coverage_diagnostics(self.dwd_like, context)
                self.assertEqual(diagnostic["routing_match"], expected)
                self.assertEqual(
                    diagnostic["final_status"],
                    "eligible" if expected else "outside_coverage",
                )

    def test_overlap_percent_uses_request_area_as_denominator(self) -> None:
        request = {"west": 10.0, "south": 50.0, "east": 20.0, "north": 54.0}
        provider = {"west": 10.0, "south": 50.0, "east": 15.0, "north": 54.0}
        self.assertEqual(coverage.bbox_overlap_percent(provider, request), 50.0)

    def test_bbox_contains_handles_wrapped_longitudes(self) -> None:
        outer = {"west": 170.0, "south": -20.0, "east": -170.0, "north": 20.0}
        inner = {"west": 175.0, "south": -10.0, "east": -175.0, "north": 10.0}
        self.assertTrue(coverage.bbox_contains(outer, inner))
        self.assertFalse(coverage.bbox_contains(inner, outer))

    def test_wms_reports_ex_geographic_bbox_source(self) -> None:
        root = ET.fromstring(
            """<WMS_Capabilities xmlns="http://www.opengis.net/wms"><Capability><Layer>
            <Layer><Name>x</Name><EX_GeographicBoundingBox>
            <westBoundLongitude>1</westBoundLongitude><eastBoundLongitude>2</eastBoundLongitude>
            <southBoundLatitude>3</southBoundLatitude><northBoundLatitude>4</northBoundLatitude>
            </EX_GeographicBoundingBox></Layer></Layer></Capability></WMS_Capabilities>"""
        )
        parsed = coverage.wms_layer_geographic_coverage(root, "x")
        self.assertEqual(parsed["bbox_source"], "EX_GeographicBoundingBox")
        self.assertEqual(parsed["crs"], "EPSG:4326")

    def test_wms_reports_crs84_and_legacy_fallback_sources(self) -> None:
        crs84 = ET.fromstring(
            """<WMS_Capabilities><Capability><Layer><Layer><Name>x</Name>
            <BoundingBox CRS="CRS:84" minx="1" miny="2" maxx="3" maxy="4"/>
            </Layer></Layer></Capability></WMS_Capabilities>"""
        )
        parsed_crs84 = coverage.wms_layer_geographic_coverage(crs84, "x")
        self.assertEqual(parsed_crs84["bbox_source"], "BoundingBox/CRS:84")
        self.assertEqual(parsed_crs84["crs"], "CRS:84")

        legacy = ET.fromstring(
            """<WMT_MS_Capabilities><Capability><Layer><Layer><Name>x</Name>
            <LatLonBoundingBox minx="1" miny="2" maxx="3" maxy="4"/>
            </Layer></Layer></Capability></WMT_MS_Capabilities>"""
        )
        parsed_legacy = coverage.wms_layer_geographic_coverage(legacy, "x")
        self.assertEqual(parsed_legacy["bbox_source"], "LatLonBoundingBox")
        self.assertEqual(parsed_legacy["crs"], "EPSG:4326")

    def test_wms_13_epsg4326_axis_order_is_lat_lon(self) -> None:
        root = ET.fromstring(
            """<WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0">
            <Capability><Layer><Layer><Name>Niederschlagsradar</Name>
            <BoundingBox CRS="EPSG:4326" minx="45" miny="2" maxx="57" maxy="18"/>
            </Layer></Layer></Capability></WMS_Capabilities>"""
        )
        parsed = coverage.wms_layer_geographic_coverage(root, "Niederschlagsradar")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["bbox"], {"west": 2.0, "south": 45.0, "east": 18.0, "north": 57.0})
        self.assertEqual(parsed["bbox_source"], "BoundingBox/EPSG:4326")

    def test_wms_11_epsg4326_axis_order_is_lon_lat(self) -> None:
        root = ET.fromstring(
            """<WMT_MS_Capabilities version="1.1.1">
            <Capability><Layer><Layer><Name>Niederschlagsradar</Name>
            <BoundingBox SRS="EPSG:4326" minx="2" miny="45" maxx="18" maxy="57"/>
            </Layer></Layer></Capability></WMT_MS_Capabilities>"""
        )
        parsed = coverage.wms_layer_geographic_coverage(root, "Niederschlagsradar")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["bbox"], {"west": 2.0, "south": 45.0, "east": 18.0, "north": 57.0})
        self.assertEqual(parsed["bbox_source"], "BoundingBox/EPSG:4326")

    def test_real_cuba_trace_bbox_is_outside_dwd_coverage(self) -> None:
        context = {
            "type": "bbox",
            "west": -92.4169921875,
            "south": 16.13026201203477,
            "east": -70.3125,
            "north": 29.017748018496047,
        }
        self.assertFalse(coverage.coverage_matches_context(self.dwd_like, context))
        diagnostic = coverage.coverage_diagnostics(self.dwd_like, context)
        self.assertFalse(diagnostic["routing_match"])
        self.assertEqual(diagnostic["final_status"], "outside_coverage")
        self.assertEqual(diagnostic["overlap_percent"], 0.0)

    def test_workspace_qualified_wms_layer_name_is_supported(self) -> None:
        root = ET.fromstring(
            """<WMS_Capabilities xmlns="http://www.opengis.net/wms">
            <Capability><Layer><Layer><Name>dwd:Niederschlagsradar</Name>
            <EX_GeographicBoundingBox>
              <westBoundLongitude>2</westBoundLongitude>
              <eastBoundLongitude>17</eastBoundLongitude>
              <southBoundLatitude>46</southBoundLatitude>
              <northBoundLatitude>56</northBoundLatitude>
            </EX_GeographicBoundingBox>
            </Layer></Layer></Capability></WMS_Capabilities>"""
        )
        parsed = coverage.wms_layer_geographic_coverage(root, "Niederschlagsradar")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["bbox_source"], "EX_GeographicBoundingBox")



if __name__ == "__main__":
    unittest.main()
