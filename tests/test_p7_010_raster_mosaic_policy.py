"""P7-010 synthetic provider-neutral multi-source mosaic regressions.

No internet, Home Assistant, private providers, physical image data or secrets.
"""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

PATH = (Path(__file__).resolve().parents[1]
        / "custom_components/weather_router/raster_mosaic_policy.py")
SPEC = importlib.util.spec_from_file_location("p7010_raster_policy", PATH)
assert SPEC and SPEC.loader
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)

VIEW = {"west": -90, "south": 15, "east": 8, "north": 56}
WORLD = {"scope": "global"}
GERMANY = {"scope": "bbox",
           "bbox": {"west": 5, "south": 46, "east": 16, "north": 56}}
CARIBBEAN = {"scope": "bbox",
             "bbox": {"west": -88, "south": 16, "east": -55, "north": 35}}
NOW = "2026-10-14T15:08:00Z"
TIMESTAMP = "2026-10-14T15:00:00Z"


def source(name, coverage=WORLD, timestamp=TIMESTAMP, *, method="radar",
           enabled=True, verified=True, quantity="precipitation_rate"):
    return {
        "source_id": name,
        "eligible": enabled,
        "verified_coverage": verified,
        "coverage": coverage,
        "resource_type": "raster_tile",
        "tile_url": "https://example.invalid/tiles/{z}/{x}/{y}.png",
        "data_time": timestamp,
        "semantics": {
            "quantity": quantity, "unit": "mm/h",
            "measurement_method": method,
            "observation_kind": "observation",
        },
        "retrieved_at": NOW,
        "attribution": name,
        "legend": {"unit": "mm/h"},
        "routing_score": [1, 0, 0],
    }


def plan(*sources, max_layers=4, **kwargs):
    return policy.plan_raster_mosaic(
        list(sources), viewport=VIEW, now=NOW,
        max_data_age_seconds=1200, max_time_delta_seconds=180,
        max_layers=max_layers,
        focus={"latitude": 21.0, "longitude": -76.0},
        **kwargs,
    )


class MosaicPlanningTests(unittest.TestCase):
    def test_germany_edge_never_displaces_world(self):
        fraction = policy.viewport_overlap(VIEW, GERMANY)
        self.assertGreater(fraction, 0)
        self.assertLess(fraction, .01)
        result = plan(source("GermanRegional", GERMANY), source("WorldWide", WORLD))
        self.assertEqual([v["source_id"] for v in result["layers"]],
                         ["WorldWide", "GermanRegional"])
        self.assertEqual(result["layers"][1]["coverage"]["west"], 5)
        self.assertEqual(result["layers"][1]["coverage_scope"], "bbox")
        self.assertIs(result["layers"][1]["coverage_verified"], True)

    def test_local_focus_wins_overlay_limit_not_country_name(self):
        regional = source("local_focus", CARIBBEAN)
        far = source("far_region", GERMANY)
        result = plan(source("world"), far, regional, max_layers=2)
        self.assertEqual([v["source_id"] for v in result["layers"]],
                         ["world", "local_focus"])
        self.assertEqual(result["limitations"][-1],
                         "Weitere Quellen wegen Ressourcenbegrenzung ausgelassen")

    def test_sources_are_dynamic_not_hardcoded(self):
        more = source("future_provider_xyz", CARIBBEAN)
        result = plan(source("broad"), source("region_1", GERMANY), more)
        self.assertEqual(len(result["layers"]), 3)
        self.assertEqual(len({v["source_id"] for v in result["layers"]}), 3)

    def test_imerg_measured_latency_rejected_at_15min_accepted_at_12h(self):
        # Observed in a private, redacted NASA provider diagnostic on
        # 2026-10-16: IMERG frame 00:30 UTC, probe at 07:00 UTC.
        # This uses synthetic public resource metadata, not archived URLs.
        candidate = source("satellite_imerg", WORLD,
                           "2026-10-16T00:30:00Z",
                           method="satellite_estimate")
        options = {
            "viewport": VIEW,
            "now": "2026-10-16T07:00:37Z",
            "max_time_delta_seconds": 180,
            "max_layers": 4,
        }
        strict = policy.plan_raster_mosaic(
            [candidate], max_data_age_seconds=900, **options)
        self.assertEqual(strict["status"], "unavailable")
        self.assertEqual(strict["layers"], [])
        measured_lag = policy.plan_raster_mosaic(
            [candidate], max_data_age_seconds=43200, **options)
        self.assertEqual(measured_lag["status"], "partial")
        self.assertEqual([x["source_id"] for x in measured_lag["layers"]],
                         ["satellite_imerg"])
        self.assertEqual(measured_lag["layers"][0]["times"]["valid_at"],
                         "2026-10-16T00:30:00Z")

    def test_stale_future_and_unknown_times_fail_closed(self):
        old = source("stale", WORLD, "2026-10-14T12:30:00Z")
        future = source("future", WORLD, "2026-10-14T15:09:00Z")
        no_time = source("unknown", WORLD, None)
        result = plan(old, future, no_time)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(len(result["layers"]), 0)
        self.assertIsNone(result["reference_time"])

    def test_unverified_and_disabled_sources_fail_closed(self):
        result = plan(source("denied", enabled=False),
                      source("guess", verified=False))
        self.assertEqual(result["layers"], [])

    def test_same_time_and_method_retained_separately(self):
        result = plan(source("region", CARIBBEAN), source("world", WORLD))
        self.assertEqual(result["layers"][0]["times"]["reference_delta_seconds"], 0)
        self.assertEqual(result["layers"][1]["times"]["reference_delta_seconds"], 0)
        self.assertEqual(result["layers"][0]["semantics"]["measurement_method"], "radar")

    def test_different_methods_are_not_mixed_or_recolored(self):
        result = plan(source("foundation", WORLD, method="satellite_estimate"),
                      source("radar", CARIBBEAN, method="radar"))
        self.assertEqual(result["layers"][0]["semantics"]["measurement_method"],
                         "satellite_estimate")
        self.assertEqual(result["layers"][1]["semantics"]["measurement_method"],
                         "radar")
        self.assertNotIn("combined_measurement", result)

    def test_temporal_mismatch_is_explicit_not_fake_synchrony(self):
        older = source("older_radar", CARIBBEAN, "2026-10-14T14:50:00Z")
        base = source("world", WORLD, TIMESTAMP)
        result = plan(base, older)
        self.assertEqual([layer["source_id"] for layer in result["layers"]], ["world"])
        self.assertFalse(any(layer["quality_note"] == "zeitlich_abweichend"
                             for layer in result["layers"]))

    def test_timeline_nearby_source_preferred(self):
        same_area = {
            "scope": "bbox",
            "bbox": {"west": -84, "south": 17, "east": -58, "north": 33},
        }
        aligned = source("aligned", same_area, "2026-10-14T15:01:00Z")
        not_aligned = source("unaligned", same_area, "2026-10-14T14:50:00Z")
        result = plan(source("world", WORLD), not_aligned, aligned, max_layers=2)
        self.assertEqual(result["layers"][1]["source_id"], "aligned")

    def test_multi_frame_source_uses_best_fresh_matching_image(self):
        regional = source("radar", CARIBBEAN)
        regional.pop("data_time")
        regional.pop("tile_url")
        regional["frames"] = [
            {"data_time": "2026-10-14T15:06:00Z",
             "tile_url": "https://example.invalid/later.png"},
            {"data_time": "2026-10-14T15:01:00Z",
             "tile_url": "https://example.invalid/aligned.png"},
            {"data_time": "2026-10-14T14:10:00Z",
             "tile_url": "https://example.invalid/stale.png"},
        ]
        result = plan(source("world", WORLD), regional)
        self.assertEqual(result["layers"][1]["tile_url"],
                         "https://example.invalid/aligned.png")
        self.assertEqual(result["layers"][1]["times"]["reference_delta_seconds"], 60)

    def test_multi_frame_falls_back_to_latest_still_fresh(self):
        regional = source("radar", CARIBBEAN)
        regional["frames"] = [
            {"data_time": "2026-10-14T15:06:00Z",
             "tile_url": "https://example.invalid/later.png"},
            {"data_time": "2026-10-14T14:50:00Z",
             "tile_url": "https://example.invalid/older.png"},
        ]
        result = plan(source("world", WORLD), regional)
        self.assertEqual([layer["source_id"] for layer in result["layers"]], ["world"])
        self.assertFalse(any(layer["quality_note"] == "zeitlich_abweichend"
                             for layer in result["layers"]))

    def test_frame_limit_and_stale_only_are_rejected(self):
        excessive = source("too_many", CARIBBEAN)
        excessive["frames"] = [{"data_time": TIMESTAMP,
                                 "tile_url": "https://example.invalid/a.png"}] * 25
        old = source("old", CARIBBEAN)
        old["frames"] = [{"data_time": "2026-10-14T12:00:00Z",
                           "tile_url": "https://example.invalid/b.png"}]
        self.assertEqual(plan(excessive, old)["layers"], [])

    def test_antimeridian_and_full_world(self):
        crossing = {"west": 170, "south": -20, "east": -170, "north": 20}
        coverage = {"scope": "bbox", "bbox":
                    {"west": 175, "south": -5, "east": -175, "north": 5}}
        self.assertGreater(policy.viewport_overlap(crossing, coverage), 0)
        self.assertEqual(policy.viewport_overlap(
            {"west": -180, "south": -85, "east": 180, "north": 85}, WORLD), 1)
        self.assertEqual(policy.viewport_overlap(VIEW, {"scope": "unknown"}), 0)

    def test_no_fabricated_complete_coverage(self):
        result = plan(source("only_germany", GERMANY))
        self.assertEqual(result["status"], "partial")
        self.assertNotIn("uncovered_regions", result)
        self.assertTrue(any("Grundversorgung" in x for x in result["limitations"]))

    def test_unknown_coverage_not_dry(self):
        result = plan(source("unknown", {"scope": "unspecified"}))
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("precipitation_amount", result)

    def test_budgets_reject_invalid_numbers(self):
        with self.assertRaises(ValueError):
            policy.plan_raster_mosaic([], viewport=VIEW, now=NOW,
                max_data_age_seconds=1200, max_time_delta_seconds=180,
                max_layers=True)

    def test_reference_time_is_distinct_from_provider_times(self):
        result = plan(source("world"), reference_time="2026-10-14T15:02:00Z")
        self.assertEqual(result["reference_time"], "2026-10-14T15:02:00Z")
        self.assertEqual(result["layers"][0]["times"]["reference_delta_seconds"], 120)


if __name__ == "__main__":
    unittest.main()
