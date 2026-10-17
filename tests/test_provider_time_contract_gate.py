"""Sperrtests: eine zentrale UTC-Grenze fuer alle 38 Provider und 280 Capabilities."""
from __future__ import annotations
import ast
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "weather_router"
REGISTRY = ROOT / "provider_time_contracts.v1.json"
MAP = ROOT / "consumer_capability_map.json"

spec = importlib.util.spec_from_file_location("wr_time_contract_test", ROOT / "time_normalization.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class UniversalProviderTimeContractTests(unittest.TestCase):
    def test_registry_covers_registered_capabilities_exactly(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        mapping = json.loads(MAP.read_text(encoding="utf-8"))
        self.assertEqual(set(registry["providers"]), set(mapping["providers"]))
        for provider, capabilities in mapping["providers"].items():
            self.assertEqual(set(registry["providers"][provider]), set(capabilities),
                             "Zeitvertrag fehlt fuer einen registrierten Provider/Capability")
        self.assertEqual(sum(map(len, mapping["providers"].values())), 280)
        self.assertEqual(len(mapping["providers"]), 38)
        module.provider_time_contracts.cache_clear()
        self.assertEqual(set(module.provider_time_contracts()["providers"]), set(mapping["providers"]))

    def test_runtime_mapping_guard_precedes_optional_provider_merge(self):
        # Der Standardkatalog muss strikt validiert werden; zusaetzliche
        # Laufzeitprovider duerfen V1/V2 nicht insgesamt deaktivieren.
        code = (ROOT / "consumer_api.py").read_text(encoding="utf-8")
        tree = ast.parse(code)
        loader = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef)
                      and node.name == "_load_mapping_sync")
        body = ast.get_source_segment(code, loader)
        self.assertLess(body.index("validate_provider_time_registry_coverage("),
                        body.index("merge_extension_capability_map(payload)"))
        self.assertEqual(code.count("validate_provider_time_registry_coverage("), 1)

    def test_unknown_runtime_source_never_gets_implicit_utc(self):
        # Dynamische Quellen duerfen Consumer nicht sperren, ihre Zeiten
        # aber ohne eigene Deklaration niemals als frische Werte erscheinen.
        self.assertEqual(module.normalize_provider_time(
            "added_source", "rainfall", "frame_time", 1792152000).reason,
            "unregistered_capability")
        self.assertIsNone(module.normalize_provider_time(
            "added_source", "rainfall", "frame_time", 1792152000).iso)

    def test_no_named_epoch_provider_exceptions_in_consumer(self):
        # Neue Provider duerfen nie eine zweite Epochentscheidung im Consumer einfuehren.
        consumer = (ROOT / "consumer_api.py").read_text(encoding="utf-8")
        tree = ast.parse(consumer)
        raster = next(node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_normalize_raster")
        self.assertNotIn("epoch_unit=", ast.get_source_segment(consumer, raster))
        self.assertIn("normalize_provider_time(", ast.get_source_segment(consumer, raster))
        for name in ("consumer_raster_mosaic_api.py", "raster_mosaic_adapter.py",
                     "raster_mosaic_policy.py", "raster_mosaic_service.py"):
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("epoch_unit=", source)

    def test_known_dwd_epoch_and_unverified_epoch(self):
        path = "timeline.frames[].time"
        dwd = module.normalize_provider_time("dwd", "radar_precipitation", path, 1792152000)
        self.assertEqual(dwd.iso, "2026-10-16T12:00:00Z")
        self.assertEqual(dwd.role, "valid_at")
        nasa = module.normalize_provider_time(
            "nasa_gibs", "satellite_precipitation_imerg_30min", "frame_time", 1792152000)
        self.assertEqual(nasa.iso, dwd.iso)
        self.assertIsNone(module.normalize_provider_time("dwd", "official_weather_warnings",
            "frame_time", 1792152000).iso)
        self.assertEqual(module.normalize_provider_time("fake_new_provider",
            "unknown", "frame_time", 1792152000).reason, "unregistered_capability")
        self.assertIsNone(module.normalize_provider_time("dwd", "radar_precipitation",
            "frame_time", 1792152000000).iso)

    def test_explicit_offsets_and_dst_fail_closed(self):
        self.assertEqual(module.iso_instant("2026-10-16T14:00:00+02:00"),
                         "2026-10-16T12:00:00Z")
        self.assertEqual(module.iso_instant("2026-10-16T06:00:00-06:00"),
                         "2026-10-16T12:00:00Z")
        self.assertIsNone(module.iso_instant("2026-10-16T12:00:00"))
        self.assertIsNone(module.provider_local_instant(
            "2026-10-25T02:30:00", iana_zone="Europe/Berlin"))
        self.assertIsNone(module.provider_local_instant(
            "2026-03-29T02:30:00", iana_zone="Europe/Berlin"))

    def test_new_capability_without_time_contract_blocks_mapping(self):
        mapping = json.loads(MAP.read_text(encoding="utf-8"))
        module.validate_provider_time_registry_coverage(mapping["providers"])
        mapping["providers"]["dwd"]["future_test_capability"] = []
        with self.assertRaisesRegex(ValueError, "capability_inventory_drift"):
            module.validate_provider_time_registry_coverage(mapping["providers"])

    def test_eumetview_and_mtg_epoch_second_paths_are_declared(self):
        for provider in ("eumetview", "eumetsat_mtg_li"):
            capability = next(iter(
                json.loads(REGISTRY.read_text(encoding="utf-8"))["providers"][provider]))
            converted = module.normalize_provider_time(
                provider, capability, "timeline.frames[].time", 1792152000)
            self.assertEqual(converted.iso, "2026-10-16T12:00:00Z")

    def test_declared_v1_times_preserve_roles_and_do_not_guess(self):
        self.assertEqual(module.normalize_provider_time("open_meteo", "temperature",
            "data_time", "2026-10-16T14:00:00+02:00").iso,
            "2026-10-16T12:00:00Z")
        self.assertEqual(module.normalize_provider_time("usgs_earthquakes",
            "earthquakes_past_day", "events[].effective",
            "2026-10-16T12:00:00Z").role, "observed_at")
        self.assertEqual(module.normalize_provider_time("noaa_nws",
            "official_weather_alerts", "events[].expires",
            "2026-10-16T12:00:00Z").role, "valid_until")
        self.assertEqual(module.normalize_provider_time("smithsonian_volcanoes",
            "weekly_volcanic_activity", "events[].effective",
            "2026-10-16T12:00:00Z").role, "published_at")
        self.assertIsNone(module.normalize_provider_time("fmi", "temperature",
            "data_time", "2026-10-16T12:00:00Z").iso)

    def test_v1_registry_guard_for_point_event_hazard_data_file(self):
        code = (ROOT / "consumer_api.py").read_text(encoding="utf-8")
        tree = ast.parse(code)
        for target in ("_normalize_event_feed", "_normalize_hazard_feed",
                       "_normalize_data_file", "_resolve_candidate"):
            node = next(x for x in tree.body if isinstance(
                x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == target)
            body = ast.get_source_segment(code, node)
            self.assertIn("_provider_time(", body, target)
            self.assertNotIn("_iso_time(raw.get(", body, target)

    def test_suvi_frame_times_are_source_declarations(self):
        for wavelength in ("094", "131", "171", "195", "284", "304"):
            converted = module.normalize_provider_time(
                "noaa_swpc", "solar_suvi_" + wavelength,
                "timeline.frames[].time", "2026-10-16T12:00:00Z")
            self.assertEqual(converted.iso, "2026-10-16T12:00:00Z")
            self.assertEqual(converted.role, "observed_at")
        source = (ROOT / "consumer_api.py").read_text(encoding="utf-8")
        self.assertIn('candidate, "timeline.frames[].time"', source)
        self.assertNotIn('_iso_time(frame.get("time"))', source)

    def test_unknown_field_cannot_become_a_fresh_instant(self):
        result = module.normalize_provider_time(
            "open_meteo", "temperature", "current.time", 1792152000)
        self.assertEqual(result.reason, "unverified_source_time_contract")
        self.assertIsNone(result.iso)


    def test_documented_point_forecast_time_contracts(self):
        # Actual central normalizer, not a replacement parser.
        cases = (
            ("met_norway", "temperature", "valid_at"),
            ("met_norway", "nowcast_precipitation", "valid_at"),
            ("smhi", "wind_speed", "valid_at"),
            ("smhi", "thunder_probability", "valid_at"),
            ("noaa_nws", "temperature", "interval_start"),
            ("noaa_nws", "precipitation_probability", "interval_start"),
        )
        for provider, capability, role in cases:
            with self.subTest(provider=provider, capability=capability):
                actual = module.normalize_provider_time(
                    provider, capability, "data_time", "2026-10-16T14:00:00+02:00")
                self.assertEqual(actual.iso, "2026-10-16T12:00:00Z")
                self.assertEqual(actual.role, role)
                self.assertIsNone(module.normalize_provider_time(
                    provider, capability, "data_time", "2026-10-16T12:00:00").iso)
                self.assertIsNone(module.normalize_provider_time(
                    provider, capability, "data_time", 1792152000).iso)
        for field, role in (("values[].interval_start", "interval_start"),
                            ("values[].interval_end", "interval_end")):
            result = module.normalize_provider_time(
                "smhi", "thunder_probability", field, "2026-10-16T12:00:00Z")
            self.assertEqual(result.iso, "2026-10-16T12:00:00Z")
            self.assertEqual(result.role, role)

    def test_point_audit_coverage_not_a_runtime_pass(self):
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        for provider, count in (("met_norway", 23), ("smhi", 15),
                                ("noaa_nws", 8)):
            cap = registry["providers"][provider]
            self.assertEqual(sum(
                item["status"] == "static_code_evidence"
                for item in cap.values()), count)
            self.assertNotIn("runtime_verified",
                             [item["status"] for item in cap.values()])
        self.assertEqual(sum(
            item["status"] == "static_code_evidence"
            for caps in registry["providers"].values()
            for item in caps.values()), 118)
        self.assertEqual(sum(
            item["status"] == "unverified"
            for caps in registry["providers"].values()
            for item in caps.values()), 162)


    def test_fmi_compact_utc_has_explicit_field_basis(self):
        # Test actual central parser for ten statically documented FMI fields.
        for capability in json.loads(REGISTRY.read_text(encoding="utf-8"))["providers"]["fmi"]:
            with self.subTest(capability=capability):
                result = module.normalize_provider_time(
                    "fmi", capability, "data_time", "20180514T000000")
                self.assertEqual(result.iso, "2018-05-14T00:00:00Z")
                self.assertEqual(result.role, "valid_at")
                self.assertEqual(result.timezone_basis, "UTC")
                for invalid in ("2018-05-14T00:00:00Z", "20180514T000000+02:00",
                                "20180514T00000", "20180230T000000",
                                "20181028T023000Z", 1526256000):
                    self.assertIsNone(module.normalize_provider_time(
                        "fmi", capability, "data_time", invalid).iso)
        self.assertIsNone(module.iso_instant("20180514T000000"))
        self.assertIsNone(module.normalize_provider_time(
            "met_norway_astronomy", "moon_phase_angle",
            "data_time", "20180514T000000").iso)
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        self.assertEqual(sum(
            cap["status"] == "static_code_evidence"
            for provider in registry["providers"].values()
            for cap in provider.values()), 118)


if __name__ == "__main__":
    unittest.main()
