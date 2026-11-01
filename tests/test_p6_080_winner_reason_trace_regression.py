"""P6-080 regression: winner reason must agree with the real trace's zero failures.

The selected candidate is marked attempted before its final selected result is
written. A pending result must not be classified as a failed provider attempt.
No Home Assistant network or private diagnostic data required.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

CORE = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
spec = importlib.util.spec_from_file_location("p6080_trace_reason", CORE / "routing_diagnostic_core.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def trace():
    return module.RoutingTraceBuilder(capability="weather.point.temperature", contract_version=1)


def add(trace_obj, key, index):
    trace_obj.add_candidate(key=key, provider_id=key.split("/")[0],
                            provider_name="Synthetic provider", capability_id="temperature",
                            resource_type="value", source_class="model",
                            order=index, routing_score=[index, 0, 0],
                            intent="weather.point.temperature")


class P6080WinnerReasonRealTrace(unittest.TestCase):
    def test_first_winner_is_not_false_fallback_before_final_status(self):
        t = trace()
        add(t, "first/temperature", 0)
        add(t, "second/temperature", 1)
        t.candidate_attempt("first/temperature")
        self.assertEqual(t.recorded_fallback_count(), 0)
        self.assertEqual(t.winner_reason(eligible_count=2), "eligible_candidate")
        t.candidate_result("first/temperature", result="selected", reason="eligible_candidate")
        self.assertEqual(t.recorded_fallback_count(), 0)
        self.assertEqual(t.winner_reason(eligible_count=2), "eligible_candidate")

    def test_finished_failure_counts_but_pending_winner_does_not(self):
        t = trace()
        add(t, "first/temperature", 0)
        add(t, "second/temperature", 1)
        t.candidate_attempt("first/temperature")
        t.candidate_result("first/temperature", result="failed", reason="temporarily_unavailable")
        t.candidate_attempt("second/temperature")
        self.assertEqual(t.recorded_fallback_count(), 1)
        self.assertEqual(t.winner_reason(eligible_count=2), "fallback_after_failure")
        t.candidate_result("second/temperature", result="selected", reason="fallback_after_failure")
        self.assertEqual(t.recorded_fallback_count(), 1)

if __name__ == "__main__":
    unittest.main()
