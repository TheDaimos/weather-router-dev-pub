"""Unit tests for the pure routing diagnostic core."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
SPEC = importlib.util.spec_from_file_location("weather_router_routing_diagnostic_core", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


class RoutingDiagnosticCoreTests(unittest.TestCase):
    def test_secret_redaction(self) -> None:
        raw = {
            "url": "https://example.invalid/data?token=secret-value&layer=radar",
            "authorization": "Bearer top-secret",
            "cookie": "session=secret",
            "nested": {"api_key": "abc123", "ok": "visible"},
        }
        safe = core.diagnostic_value(raw)
        self.assertNotIn("secret-value", str(safe))
        self.assertNotIn("top-secret", str(safe))
        self.assertNotIn("abc123", str(safe))
        self.assertEqual(safe["nested"]["ok"], "visible")

    def test_url_summary_never_contains_full_url_or_query_values(self) -> None:
        summary = core.safe_url_summary(
            "https://tiles.example.invalid/wms/{z}/{x}/{y}?layer=radar&token=secret"
        )
        self.assertEqual(summary["host"], "tiles.example.invalid")
        self.assertIn("layer", summary["query_keys"])
        self.assertNotIn("token", summary["query_keys"])
        self.assertIn("{z}", summary["template_tokens"])
        self.assertNotIn("secret", str(summary))

    def test_trace_schema_and_candidate_decision(self) -> None:
        trace = core.RoutingTraceBuilder(
            capability="weather.radar.precipitation",
            contract_version=1,
        )
        trace.set_context({"type": "bbox", "west": 47.0, "south": 7.0, "east": 52.0, "north": 12.0})
        trace.set_request(
            family="radar",
            phenomena=["precipitation"],
            resource_types=["raster_tile"],
            context_type="bbox",
            time_mode="latest",
            requirements={"resource_types": ["raster_tile"]},
        )
        trace.add_candidate(
            key="dwd/radar_precipitation",
            provider_id="dwd",
            provider_name="DWD",
            capability_id="radar_precipitation",
            resource_type="raster_tile",
            source_class="observation_forecast",
            order=0,
            network_targets=[{"host": "maps.dwd.de", "port": 443, "scheme": "https"}],
        )
        trace.candidate_check("dwd/radar_precipitation", "coverage", False, "outside_coverage")
        trace.candidate_result(
            "dwd/radar_precipitation",
            result="rejected",
            reason="outside_coverage",
            duration_ms=2.5,
        )
        trace.set_decision(status="unavailable", code="outside_coverage")
        result = trace.finish()
        self.assertEqual(result["schema"], "weather_router.routing_diagnostic.v1")
        self.assertEqual(result["decision"]["code"], "outside_coverage")
        self.assertEqual(result["candidates"][0]["checks"]["coverage"]["passed"], False)
        self.assertEqual(result["network"]["observed_call_count"], None)
        self.assertLess(result["meta"]["duration_ms"], 1000)

    def test_candidate_trace_preserves_unit_when_present(self) -> None:
        trace = core.RoutingTraceBuilder(
            capability="weather.precipitation.layer",
            contract_version=1,
        )
        trace.add_candidate(
            key="nasa_gibs/satellite_precipitation_imerg_30min",
            provider_id="nasa_gibs",
            provider_name="NASA GIBS",
            capability_id="satellite_precipitation_imerg_30min",
            resource_type="raster_tile",
            source_class="observation",
            order=0,
            data_origin="satellite",
            measurement_method="satellite_precipitation_estimate",
            observation_kind="estimate",
            quantity="precipitation_rate",
            unit="mm/h",
            routing_score=[2, 0, 1],
        )
        result = trace.finish(status="ready")
        self.assertEqual(result["candidates"][0]["unit"], "mm/h")

    def test_candidate_trace_marks_standard_core_and_extension_scope(self) -> None:
        trace = core.RoutingTraceBuilder(
            capability="weather.lightning.observed.events",
            contract_version=1,
        )
        trace.add_candidate(
            key="fmi_lightning/lightning_strikes_observed",
            provider_id="fmi_lightning",
            provider_name="FMI",
            capability_id="lightning_strikes_observed",
            resource_type="event_feed",
            source_class="observation",
            order=0,
        )
        trace.add_candidate(
            key="local_lightning/lightning_strikes_observed",
            provider_id="local_lightning",
            provider_name="Local Lightning",
            capability_id="lightning_strikes_observed",
            resource_type="event_feed",
            source_class="observation",
            order=1,
            candidate_scope="extension",
            extension_id="local_lightning_ext",
        )
        result = trace.finish(status="ready")
        self.assertEqual(result["candidates"][0]["candidate_scope"], "standard_core")
        self.assertIsNone(result["candidates"][0]["extension_id"])
        self.assertEqual(result["candidates"][1]["candidate_scope"], "extension")
        self.assertEqual(result["candidates"][1]["extension_id"], "local_lightning_ext")

    def test_trace_meta_can_carry_build_and_loader(self) -> None:
        trace = core.RoutingTraceBuilder(
            capability="weather.precipitation.layer",
            contract_version=1,
            build_version="0.10.92",
            loader_revision="0.10-loader-95",
        )
        result = trace.finish(status="ready")
        self.assertEqual(result["meta"]["build_version"], "0.10.92")
        self.assertEqual(result["meta"]["loader_revision"], "0.10-loader-95")

    def test_raster_summary_is_small_and_url_safe(self) -> None:
        payload = {
            "tile_url": "https://tiles.example.invalid/{z}/{x}/{y}?token=nope",
            "tile_size": 256,
            "max_zoom": 11,
            "legend": {
                "title": "Niederschlag",
                "url": "https://legend.example.invalid/legend.png",
                "style": "precipitation",
            },
            "timeline": {
                "default": "current",
                "default_index": 1,
                "current_index": 1,
                "loop": True,
                "frames": [
                    {"time": "2026-10-01T08:00:00Z", "tile_url": "https://x/1", "kind": "observation"},
                    {"time": "2026-10-01T08:05:00Z", "tile_url": "https://x/2", "kind": "forecast"},
                ],
            },
        }
        summary = core.resource_summary("raster_tile", payload, {})
        self.assertEqual(summary["timeline"]["frame_count"], 2)
        self.assertEqual(summary["timeline"]["default"], "current")
        self.assertEqual(summary["timeline"]["default_index"], 1)
        self.assertEqual(summary["timeline"]["current_index"], 1)
        self.assertEqual(summary["timeline"]["frame_kinds"], ["forecast", "observation"])
        self.assertEqual(summary["legend"]["style"], "precipitation")
        self.assertEqual(summary["tile_url"]["host"], "tiles.example.invalid")
        self.assertNotIn("nope", str(summary))

    def test_resource_summaries_cover_all_current_resource_classes(self) -> None:
        cases = {
            "value": (
                {"values": {"weather.point.temperature": {"value": 12.3, "unit": "°C", "data_time": "2026-10-01T08:00:00Z"}}},
                "value_count",
            ),
            "event_feed": (
                {"events": [{"event_type": "lightning", "severity": None}], "event_count": 1},
                "event_count",
            ),
            "hazard_feed": (
                {"events": [{"hazard_type": "tornado", "severity": "severe", "geometry": {"type": "Point"}}], "event_count": 1},
                "event_count",
            ),
            "data_file": (
                {"format": "netcdf4", "url": "https://data.example.invalid/a.nc?token=secret", "transport": "direct", "size_bytes": 42},
                "format",
            ),
            "image_sequence": (
                {"frames": [{"time": "2026-10-01T08:00:00Z", "url": "https://img.example.invalid/a.png"}], "default_index": 0},
                "timeline",
            ),
            "live_stream": (
                {"url": "https://stream.example.invalid/watch?id=1&token=secret", "transport": "direct", "title": "Live"},
                "url",
            ),
            "planetary_tile": (
                {"body": "moon", "tile_url": "https://moon.example.invalid/{z}/{x}/{y}", "min_zoom": 0, "max_zoom": 8, "tile_size": 256, "crs": "EPSG:4326"},
                "body",
            ),
            "future_unknown_type": (
                {"alpha": 1, "beta": 2},
                "keys",
            ),
        }
        for resource_type, (payload, required_key) in cases.items():
            with self.subTest(resource_type=resource_type):
                summary = core.resource_summary(resource_type, payload, {})
                self.assertEqual(summary["type"], resource_type)
                self.assertIn(required_key, summary)
                self.assertNotIn("secret", str(summary))

    def test_decision_codes_are_recorded_without_semantic_reinterpretation(self) -> None:
        codes = (
            "outside_coverage",
            "no_eligible_provider",
            "temporarily_unavailable",
            "rate_limited",
            "profile_filtered",
            "provider_disabled",
            "domain_disabled",
            "source_stale",
            "requirements_not_met",
        )
        for code in codes:
            with self.subTest(code=code):
                trace = core.RoutingTraceBuilder(
                    capability="weather.test.example",
                    contract_version=1,
                )
                trace.set_decision(status="unavailable", code=code)
                result = trace.finish()
                self.assertEqual(result["decision"]["status"], "unavailable")
                self.assertEqual(result["decision"]["code"], code)

    def test_fallback_trace_preserves_deterministic_order(self) -> None:
        trace = core.RoutingTraceBuilder(
            capability="weather.radar.precipitation",
            contract_version=1,
        )
        for order, provider in enumerate(("regional_a", "global_b")):
            trace.add_candidate(
                key=f"{provider}/radar",
                provider_id=provider,
                provider_name=provider,
                capability_id="radar",
                resource_type="raster_tile",
                source_class="observation",
                order=order,
            )
        trace.candidate_attempt("regional_a/radar")
        trace.candidate_provider_contact("regional_a/radar")
        trace.candidate_result(
            "regional_a/radar",
            result="rejected",
            reason="outside_coverage",
            duration_ms=1.0,
        )
        trace.candidate_attempt("global_b/radar")
        trace.candidate_provider_contact("global_b/radar")
        trace.candidate_result(
            "global_b/radar",
            result="selected",
            reason="fallback_after_failure",
            duration_ms=2.0,
        )
        trace.set_decision(
            status="ready",
            selected_provider="global_b",
            selected_capability="radar",
            selected_index=1,
            fallback_count=1,
            reason_code="fallback_after_failure",
        )
        result = trace.finish()
        self.assertEqual(
            [item["provider_id"] for item in result["candidates"]],
            ["regional_a", "global_b"],
        )
        self.assertEqual(result["decision"]["selected_provider"], "global_b")
        self.assertEqual(result["decision"]["fallback_count"], 1)
        self.assertEqual(result["performance"]["providers_contacted"], 2)
        self.assertTrue(result["candidates"][0]["provider_contacted"])
        self.assertTrue(result["candidates"][1]["provider_contacted"])

    def test_declared_network_targets_do_not_claim_observed_network_calls(self) -> None:
        trace = core.RoutingTraceBuilder(
            capability="weather.radar.precipitation",
            contract_version=1,
        )
        trace.add_candidate(
            key="dwd/radar",
            provider_id="dwd",
            provider_name="DWD",
            capability_id="radar",
            resource_type="raster_tile",
            source_class="observation",
            order=0,
            network_targets=[
                {
                    "scheme": "https",
                    "host": "maps.dwd.de",
                    "port": 443,
                    "purpose": "WMS",
                }
            ],
        )
        result = trace.finish(status="unavailable", code="temporarily_unavailable")
        self.assertEqual(result["network"]["instrumentation"], "declared_targets_only")
        self.assertEqual(result["network"]["observed_call_count"], None)
        self.assertEqual(result["network"]["declared_targets"][0]["host"], "maps.dwd.de")

    def test_cache_trace_accepts_provider_reported_hit_and_miss(self) -> None:
        trace = core.RoutingTraceBuilder(
            capability="weather.radar.precipitation",
            contract_version=1,
        )
        for order, hit in enumerate((True, False)):
            key = f"p{order}/raster"
            trace.add_candidate(
                key=key,
                provider_id=f"p{order}",
                provider_name=f"P{order}",
                capability_id="raster",
                resource_type="raster_tile",
                source_class="observation",
                order=order,
            )
            trace.candidate_coverage(
                key,
                {
                    "machine_coverage": True,
                    "routing_match": True,
                    "cache": {
                        "type": "wms_get_capabilities",
                        "hit": hit,
                        "age_seconds": 5.0 if hit else 0.0,
                        "ttl_seconds": 300,
                    },
                },
            )
        result = trace.finish(status="ready")
        self.assertEqual(len(result["cache"]["entries"]), 2)
        self.assertTrue(result["cache"]["entries"][0]["hit"])
        self.assertFalse(result["cache"]["entries"][1]["hit"])

    def test_error_trace_records_network_failure_class_without_traceback_payload(self) -> None:
        trace = core.RoutingTraceBuilder(
            capability="weather.test.example",
            contract_version=1,
        )
        trace.add_error(
            stage="provider_resolution",
            code="temporarily_unavailable",
            message="https://api.example.invalid/data?token=secret failed",
            exception_type="TimeoutError",
        )
        result = trace.finish(status="unavailable", code="temporarily_unavailable")
        error = result["errors"][0]
        self.assertEqual(error["exception_type"], "TimeoutError")
        self.assertEqual(error["code"], "temporarily_unavailable")
        self.assertNotIn("secret", str(error))
        self.assertNotIn("traceback", error)

    def test_event_and_hazard_summaries_preserve_counts_not_full_events(self) -> None:
        events = [
            {
                "id": str(index),
                "event_type": "lightning",
                "hazard_type": "tornado",
                "severity": "severe",
                "geometry": {"type": "Point"},
                "description": "x" * 5000,
            }
            for index in range(300)
        ]
        summary = core.resource_summary(
            "hazard_feed",
            {
                "events": events,
                "event_count": 300,
                "unfiltered_event_count": 350,
                "source_count": 2,
            },
            {},
        )
        self.assertEqual(summary["event_count"], 300)
        self.assertEqual(summary["unfiltered_event_count"], 350)
        self.assertEqual(summary["geometry_count"], 300)
        self.assertNotIn("description", summary)


if __name__ == "__main__":
    unittest.main()
