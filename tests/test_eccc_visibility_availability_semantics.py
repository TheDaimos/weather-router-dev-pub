"""Regression guard for ECCC visibility availability/coverage semantics."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = (
    ROOT
    / "custom_components"
    / "weather_router"
    / "providers"
    / "eccc_geomet.py"
)
CONSUMER = ROOT / "custom_components" / "weather_router" / "consumer_api.py"


class EcccVisibilityAvailabilitySemanticsTest(unittest.TestCase):
    """Missing live observations must not be presented as spatial non-coverage."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.provider_source = PROVIDER.read_text(encoding="utf-8")
        cls.consumer_source = CONSUMER.read_text(encoding="utf-8")

    def test_empty_realtime_result_keeps_coverage_unknown(self) -> None:
        self.assertIn('coverage_status: str = "unknown"', self.provider_source)
        self.assertIn(
            'unavailable_code: str = "temporarily_unavailable"',
            self.provider_source,
        )
        self.assertIn('"coverage_status": coverage_status', self.provider_source)
        self.assertIn('"unavailable_code": unavailable_code', self.provider_source)

    def test_distance_gate_can_still_report_real_runtime_noncoverage(self) -> None:
        self.assertIn(
            'coverage_status="outside_coverage",\n'
            '                unavailable_code="outside_coverage"',
            self.provider_source,
        )

    def test_consumer_distinguishes_coverage_from_temporary_availability(self) -> None:
        resolver = self.consumer_source.index(
            "async def _resolve_candidate("
        )
        anchor = self.consumer_source.index(
            '    if mode == "value":',
            resolver,
        )
        end = self.consumer_source.index(
            '    if mode == "event_feed":',
            anchor,
        )
        point_resolver = self.consumer_source[anchor:end]

        coverage_pos = point_resolver.index(
            'if result.get("coverage_status") == "outside_coverage":'
        )
        availability_pos = point_resolver.index(
            'if result.get("available") is False:'
        )
        temporary_pos = point_resolver.index(
            'if result.get("unavailable_code") == "temporarily_unavailable":'
        )
        self.assertLess(coverage_pos, availability_pos)
        self.assertGreater(temporary_pos, availability_pos)
        self.assertIn(
            'CandidateUnavailable(\n'
            '                    "temporarily_unavailable",\n'
            '                    retryable=True,',
            point_resolver,
        )


if __name__ == "__main__":
    unittest.main()
