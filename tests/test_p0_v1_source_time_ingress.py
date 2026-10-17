"""P0: echte, aus dem Consumer extrahierte V1-Verbraucherfunktionen.

Ohne Home Assistant, Provider-Netzzugriff oder private Erweiterungen.
Getestet wird der produktive Funktionsrumpf, nicht eine Nachimplementierung.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
PACKAGE = "wr_p0_v1_time_ingress_isolated"
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = package
normalizer = importlib.import_module(PACKAGE + ".time_normalization")
source = (ROOT / "consumer_api.py").read_text(encoding="utf-8")
tree = ast.parse(source)
selected = {
    "_provider_time", "_normalize_event_feed", "_normalize_hazard_feed",
    "_timeline_frames", "_normalize_image_sequence", "_normalize_data_file",
}
functions = [
    node for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    and node.name in selected
]
assert len(functions) == len(selected)
program = ast.Module(body=[
    ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
    *functions
], type_ignores=[])
namespace = {
    "__name__": PACKAGE + ".consumer_api",
    "__package__": PACKAGE,
    "_safe_public_url": lambda url: url if isinstance(url, str) and url.startswith(
        "https://example.invalid/") else None,
    "_source_provenance": lambda *args: {},
    "_load_hazard_types_sync": lambda: {"hazard_types": {"weather_warning": {}}},
    "_generic_hazard_type_for_public_id": lambda _: "weather_warning",
    "_FLOOD_SEMANTIC_CLASSES": (),
    "_FLOOD_MATCH_SCOPES": (),
    "_TROPICAL_SYSTEM_CLASSES": (),
    "_TROPICAL_REGIONAL_TERMS": (),
    "_TROPICAL_CLASSIFICATION_SOURCES": (),
    "_EARTHQUAKE_SEMANTIC_CLASSES": (),
    "_EARTHQUAKE_CATALOG_SELECTIONS": (),
    "_VOLCANO_SEMANTIC_CLASSES": (),
    "_TSUNAMI_SEMANTIC_CLASSES": (),
    "_TSUNAMI_ALERT_STAGES": (),
    "_TSUNAMI_WAVE_EVIDENCE": (),
}
class CandidateUnavailable(Exception):
    def __init__(self, code, *, retryable, message):
        super().__init__(message)
        self.code = code
namespace["CandidateUnavailable"] = CandidateUnavailable
exec(compile(ast.fix_missing_locations(program), str(ROOT / "consumer_api.py"), "exec"),
     namespace)


def candidate(provider, capability):
    return types.SimpleNamespace(
        provider=types.SimpleNamespace(id=provider),
        capability=types.SimpleNamespace(id=capability, source_class="observation"),
        public_id="weather.precipitation.layer",
    )


class UniversalV1SourceTimeTests(unittest.TestCase):
    def test_declared_provider_time_and_declared_format_are_mandatory(self):
        func = namespace["_provider_time"]
        errors = set()
        when = func(candidate("open_meteo", "temperature"), "data_time",
                    "2026-10-16T14:00:00+02:00", {}, errors)
        self.assertEqual(when, "2026-10-16T12:00:00Z")
        self.assertFalse(errors)
        unknown = func(candidate("fmi", "temperature"), "data_time",
                       "2026-10-16T12:00:00Z", {}, errors)
        self.assertIsNone(unknown)
        self.assertIn("unverified_source_time_contract", errors)

    def test_absent_optional_timestamp_is_not_a_contract_error(self):
        errors = set()
        self.assertIsNone(namespace["_provider_time"](
            candidate("fmi", "temperature"), "valid_time", None, {}, errors))
        self.assertEqual(errors, set())

    def test_hazard_warning_preserves_distinct_validity_and_issue_time(self):
        c = candidate("noaa_nws", "official_weather_alerts")
        payload, latest = namespace["_normalize_hazard_feed"](c, {
            "events": [{
                "id": "warning", "hazard_type": "weather_warning",
                "effective": "2026-10-16T14:00:00+02:00",
                "sent": "2026-10-16T10:00:00Z",
                "expires": "2026-10-16T17:00:00Z",
            }]
        })
        event = payload["events"][0]
        self.assertEqual(event["effective"], "2026-10-16T12:00:00Z")
        self.assertEqual(event["sent"], "2026-10-16T10:00:00Z")
        self.assertEqual(event["expires"], "2026-10-16T17:00:00Z")
        self.assertEqual(latest, "2026-10-16T12:00:00Z")
        self.assertNotIn("time_normalization_error", payload)

    def test_issued_only_warning_must_not_invent_event_start(self):
        payload, latest = namespace["_normalize_hazard_feed"](
            candidate("noaa_nws", "official_weather_alerts"), {
                "events": [{"id": "w", "hazard_type": "weather_warning",
                            "sent": "2026-10-16T10:00:00Z"}]})
        self.assertIsNone(payload["events"][0]["effective"])
        self.assertIsNone(latest)

    def test_unverified_hazard_event_does_not_claim_validity(self):
        payload, _ = namespace["_normalize_hazard_feed"](
            candidate("fmi", "temperature"), {
                "events": [{"id": "w", "hazard_type": "weather_warning",
                            "effective": "2026-10-16T10:00:00Z"}]})
        self.assertIsNone(payload["events"][0]["effective"])
        self.assertEqual(payload["time_normalization_error"],
                         "unverified_source_time_contract")

    def test_unknown_event_observation_cannot_turn_fresh(self):
        payload, latest = namespace["_normalize_event_feed"](
            candidate("fmi", "temperature"), {"events": [
                {"id": "e1", "event_type": "lightning",
                 "observed_at": "2026-10-16T12:00:00Z"}]})
        self.assertEqual(payload["events"], [])
        self.assertIsNone(latest)
        self.assertEqual(payload["time_normalization_error"],
                         "unverified_source_time_contract")

    def test_suvi_images_retain_source_proven_utc(self):
        frame = {"time": "2026-10-16T12:00:00Z",
                 "image_url": "https://example.invalid/suvi.png"}
        payload, latest = namespace["_normalize_image_sequence"](
            candidate("noaa_swpc", "solar_suvi_094"),
            {"timeline": {"frames": [frame]}})
        self.assertEqual(latest, "2026-10-16T12:00:00Z")
        self.assertEqual(payload["frames"][0]["time"], latest)
        self.assertNotIn("time_normalization_error", payload)

    def test_undocumented_datafile_time_does_not_become_observation(self):
        payload, latest = namespace["_normalize_data_file"](
            candidate("noaa_swpc", "aurora_ovation_latest"),
            {"url": "https://example.invalid/grid.json", "format": "json",
             "data_time": "2026-10-16T12:00:00Z",
             "valid_time": "2026-10-16T12:30:00Z"})
        self.assertIsNone(latest)
        self.assertIsNone(payload["valid_time"])
        self.assertEqual(payload["time_normalization_error"],
                         "unverified_source_time_contract")


if __name__ == "__main__":
    unittest.main()
