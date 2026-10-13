"""Regression coverage for P5-AVIATION-60 provider-contact diagnostics hotfix."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRACE_PATH = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
CONSUMER_PATH = ROOT / "custom_components" / "weather_router" / "consumer_api.py"
CONST_PATH = ROOT / "custom_components" / "weather_router" / "const.py"
LAB_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER_PATH = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"


from wr_public_version_contract import assert_current_version_surfaces

class P5AviationProviderContactDiagnosticsHotfixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.trace = TRACE_PATH.read_text(encoding="utf-8")
        cls.consumer = CONSUMER_PATH.read_text(encoding="utf-8")
        cls.const = CONST_PATH.read_text(encoding="utf-8")
        cls.lab = LAB_PATH.read_text(encoding="utf-8")
        cls.loader = LOADER_PATH.read_text(encoding="utf-8")

    def test_candidate_attempt_no_longer_counts_provider_contact(self) -> None:
        start = self.trace.index("    def candidate_attempt(")
        end = self.trace.index("    def candidate_provider_contact(", start)
        block = self.trace[start:end]
        self.assertIn('item["attempted"] = True', block)
        self.assertNotIn("providers_contacted", block)

    def test_real_provider_contact_is_idempotent_per_candidate(self) -> None:
        start = self.trace.index("    def candidate_provider_contact(")
        end = self.trace.index("    def candidate_freshness(", start)
        block = self.trace[start:end]
        self.assertIn('if item.get("provider_contacted"):', block)
        self.assertIn('item["provider_contacted"] = True', block)
        self.assertIn(
            'self.data["performance"]["providers_contacted"] += 1',
            block,
        )

    def test_candidate_diagnostics_expose_provider_contacted_flag(self) -> None:
        self.assertIn('"provider_contacted": False', self.trace)

    def test_actual_provider_methods_mark_contact(self) -> None:
        self.assertGreaterEqual(
            self.consumer.count("trace.candidate_provider_contact(key)"),
            6,
        )

    def test_aviation_point_guard_precedes_provider_contact(self) -> None:
        mode = self.consumer.index('    if mode == "hazard_feed":')
        guard = self.consumer.index(
            "candidate.public_id in _AVIATION_PUBLIC_IDS",
            mode,
        )
        contact = self.consumer.index(
            "trace.candidate_provider_contact(key)",
            guard,
        )
        fetch = self.consumer.index(
            "result = await fetch(hass, candidate.capability.id, **kwargs)",
            guard,
        )
        self.assertLess(guard, contact)
        self.assertLess(contact, fetch)
        block = self.consumer[guard:contact]
        self.assertIn('"requirements_not_met"', block)
        self.assertIn("retryable=False", block)

    def test_version_surfaces_are_010139_loader142(self) -> None:
        assert_current_version_surfaces(self, self.const, self.lab, self.loader)


if __name__ == "__main__":
    unittest.main()
