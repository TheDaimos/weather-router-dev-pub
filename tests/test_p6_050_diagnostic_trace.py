"""P6-050: runtime trace decisions distinguish attempts from eligibility skips."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

CORE = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
spec = importlib.util.spec_from_file_location("wr_p6050_diagnostic", CORE / "routing_diagnostic_core.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def builder():
    return module.RoutingTraceBuilder(capability="weather.synthetic.layer", contract_version=1)


def candidate(trace, name, score):
    trace.add_candidate(
        key=f"{name}/synthetic", provider_id=name, provider_name=name,
        capability_id="synthetic", resource_type="raster_tile",
        source_class="observation", order=score,
        routing_score=[score, 0, 0], intent="weather.synthetic.layer",
    )


class P6050Diagnostics(unittest.TestCase):
    def test_rejection_records_reason_without_contact(self):
        trace = builder()
        candidate(trace, "globally_disabled", 0)
        trace.candidate_check("globally_disabled/synthetic", "provider", False, "provider_disabled")
        trace.candidate_result("globally_disabled/synthetic", result="rejected", reason="provider_disabled")
        row = trace.data["candidates"][0]
        self.assertEqual(row["checks"]["provider"]["reason"], "provider_disabled")
        self.assertEqual(row["reason"], "provider_disabled")
        self.assertFalse(row["attempted"])
        self.assertEqual(trace.recorded_fallback_count(), 0)

    def test_attempted_failure_counts_but_unattempted_skip_does_not(self):
        trace = builder()
        for index, name in enumerate(("skipped", "failed", "selected")):
            candidate(trace, name, index)
        trace.candidate_result("skipped/synthetic", result="rejected", reason="requirements_not_met")
        trace.candidate_attempt("failed/synthetic")
        trace.candidate_result("failed/synthetic", result="rejected", reason="outside_coverage")
        trace.candidate_attempt("selected/synthetic")
        trace.candidate_result("selected/synthetic", result="selected", reason="fallback_candidate")
        trace.set_decision(
            status="ready", selected_provider="selected", selected_capability="synthetic",
            selected_index=2, fallback_count=trace.recorded_fallback_count(),
            reason_code="fallback_candidate",
        )
        done = trace.finish(status="ready")
        self.assertEqual(done["decision"]["selected_index"], 2)
        self.assertEqual(done["decision"]["fallback_count"], 1)
        self.assertEqual(done["decision"]["reason_code"], "fallback_candidate")
        self.assertEqual([r["result"] for r in done["candidates"]], ["rejected", "rejected", "selected"])
        self.assertEqual([r["attempted"] for r in done["candidates"]], [False, True, True])

    def test_winner_reason_uses_attempts_not_skipped_position(self):
        trace = builder()
        candidate(trace, "skipped", 0)
        candidate(trace, "winner", 1)
        trace.candidate_result("skipped/synthetic", result="rejected", reason="requirements_not_met")
        self.assertEqual(trace.winner_reason(eligible_count=2), "eligible_candidate")
        self.assertEqual(trace.recorded_fallback_count(), 0)
        trace.candidate_attempt("skipped/synthetic")
        self.assertEqual(trace.winner_reason(eligible_count=2), "fallback_after_failure")
        self.assertEqual(
            trace.winner_reason(eligible_count=2, rate_limited=True),
            "fallback_after_rate_limit",
        )

    def test_only_eligible_winner_reason(self):
        trace = builder()
        candidate(trace, "winner", 0)
        self.assertEqual(trace.winner_reason(eligible_count=1), "only_eligible_candidate")

    def test_provider_contact_is_distinct_from_attempt(self):
        trace = builder()
        candidate(trace, "provider", 0)
        trace.candidate_attempt("provider/synthetic")
        self.assertEqual(trace.data["performance"]["providers_contacted"], 0)
        trace.candidate_provider_contact("provider/synthetic")
        trace.candidate_provider_contact("provider/synthetic")
        self.assertEqual(trace.data["performance"]["providers_contacted"], 1)

    def test_aggregate_failed_attempts_and_multiple_selected_sources(self):
        trace = builder()
        for index, name in enumerate(("a", "b", "c")):
            candidate(trace, name, index)
            trace.candidate_attempt(f"{name}/synthetic")
        trace.candidate_result("a/synthetic", result="selected", reason="aggregate_source")
        trace.candidate_result("b/synthetic", result="failed", reason="rate_limited")
        trace.candidate_result("c/synthetic", result="selected", reason="aggregate_source")
        self.assertEqual(trace.recorded_fallback_count(), 1)

    def test_trace_redaction_and_bounded_schema(self):
        trace = builder()
        trace.add_error(stage="provider_resolution", code="temporarily_unavailable",
                        message="GET https://host.invalid/path?api_key=private_synthetic_value")
        output = trace.finish(status="unavailable", code="temporarily_unavailable")
        self.assertEqual(output["schema"], module.ROUTING_DIAGNOSTIC_SCHEMA)
        self.assertNotIn("private_synthetic_value", str(output))
        self.assertEqual(output["decision"]["status"], "unavailable")

if __name__ == "__main__":
    unittest.main()
