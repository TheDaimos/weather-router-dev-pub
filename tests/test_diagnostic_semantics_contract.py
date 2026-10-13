"""P1-100 diagnostic contract tests for normalized routing semantics."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "weather_router"
CORE_PATH = COMPONENT / "routing_diagnostic_core.py"
API_PATH = COMPONENT / "consumer_api.py"
FRONTEND_PATH = COMPONENT / "frontend" / "weather-router-lab-routing-diagnostics.js"
SCHEMA_PATH = ROOT / "contracts" / "diagnostics" / "routing_diagnostic.v1.schema.json"

SPEC = importlib.util.spec_from_file_location("weather_router_routing_diagnostic_core_p1100", CORE_PATH)
assert SPEC is not None and SPEC.loader is not None
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


class DiagnosticSemanticsContractTest(unittest.TestCase):
    """All P1-normalized candidate axes must be visible in routing diagnostics."""

    def test_candidate_trace_preserves_full_normalized_semantics(self) -> None:
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
            intent="weather.precipitation.layer",
            topics=["precipitation", "satellite_imagery"],
            data_origin="satellite",
            measurement_method="satellite_precipitation_estimate",
            observation_kind="estimate",
            quantity="precipitation_rate",
            unit="mm/h",
            time_semantics={
                "request_time_mode": "latest",
                "data_time": "optional_runtime",
                "valid_time": "not_applicable",
            },
            coverage_semantics={
                "coverage_scope": "bbox",
                "coverage_evidence": "machine_readable_runtime",
                "routing_authority": "hard",
                "coordinate_space": "earth",
                "endpoint_reachability_is_coverage": False,
            },
            routing_score=[2, 0, 1],
        )
        trace.candidate_freshness(
            "nasa_gibs/satellite_precipitation_imerg_30min",
            {
                "data_time": "2026-10-02T08:00:00Z",
                "fetched_at": "2026-10-02T08:05:00Z",
                "age_seconds": 300.0,
                "max_age_seconds": None,
                "stale": None,
            },
        )
        result = trace.finish(status="ready")
        candidate = result["candidates"][0]

        self.assertEqual(candidate["intent"], "weather.precipitation.layer")
        self.assertEqual(candidate["topics"], ["precipitation", "satellite_imagery"])
        self.assertEqual(candidate["resource_type"], "raster_tile")
        self.assertEqual(candidate["data_origin"], "satellite")
        self.assertEqual(candidate["measurement_method"], "satellite_precipitation_estimate")
        self.assertEqual(candidate["observation_kind"], "estimate")
        self.assertEqual(candidate["quantity"], "precipitation_rate")
        self.assertEqual(candidate["unit"], "mm/h")
        self.assertEqual(candidate["time_semantics"]["request_time_mode"], "latest")
        self.assertEqual(candidate["coverage_semantics"]["routing_authority"], "hard")
        self.assertEqual(candidate["freshness"]["age_seconds"], 300.0)
        self.assertEqual(candidate["routing_score"], [2, 0, 1])

    def test_consumer_api_populates_topic_intent_time_coverage_and_freshness(self) -> None:
        source = API_PATH.read_text(encoding="utf-8")
        for marker in (
            "def _candidate_topics(",
            "intent=public_id",
            "topics=_candidate_topics(mapping, candidate)",
            "time_semantics=(",
            "coverage_semantics=(",
            "trace.candidate_freshness(",
        ):
            self.assertIn(marker, source)

    def test_frontend_and_exports_show_all_required_p1_100_axes(self) -> None:
        source = FRONTEND_PATH.read_text(encoding="utf-8")
        for marker in (
            "Intent / Topic",
            "Coverage-Vertrag",
            "Freshness",
            "time_semantics",
            "coverage_semantics",
            '"intent","topics","provider","capability","resource_type"',
            '"freshness","routing_score","coverage_runtime"',
        ):
            self.assertIn(marker, source)

    def test_diagnostic_schema_requires_normalized_candidate_fields(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        required = set(schema["properties"]["candidates"]["items"]["required"])
        self.assertTrue(
            {
                "intent",
                "topics",
                "resource_type",
                "data_origin",
                "measurement_method",
                "observation_kind",
                "quantity",
                "unit",
                "time_semantics",
                "coverage_semantics",
                "freshness",
                "routing_score",
                "reason",
            }
            <= required
        )


if __name__ == "__main__":
    unittest.main()
