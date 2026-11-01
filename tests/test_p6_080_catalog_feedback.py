"""P6-080: Consumer catalog exposes useful progress and duration feedback.

Guard the UI regression with stable DOM/status contract assertions. GitHub Actions
runs syntax validation separately; this test makes no browser-performance claim.
"""
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1]
          / "custom_components/weather_router/frontend/weather-router-lab-consumer-api.js")


class P6080CatalogFeedback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")

    def test_three_visual_states_and_accessible_status(self):
        for expected in (
            'catalogFeedback: null',
            'Katalog wird geladen …',
            'Katalog geladen · ',
            'Katalog konnte nicht geladen werden:',
            'role="status" aria-live="polite"',
            'consumer-api-refresh-feedback.loading',
            'consumer-api-refresh-feedback.ok',
            'consumer-api-refresh-feedback.error',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, self.source)

    def test_duration_is_measured_and_present_in_audit_event(self):
        self.assertIn("const startedAt = Date.now();", self.source)
        self.assertIn("Date.now() - startedAt", self.source)
        self.assertIn("duration_ms: durationMs", self.source)
        self.assertIn('consumer_api_catalog_ready', self.source)
        self.assertIn('toLocaleTimeString("de-DE")', self.source)

    def test_button_disables_while_loading_and_prevents_duplicate_requests(self):
        self.assertIn('if (state.loading) return null;', self.source)
        self.assertIn('state.loading = true;', self.source)
        self.assertIn('state.loading = false;', self.source)
        self.assertIn('state.catalogFeedback = { kind:"loading"', self.source)
        self.assertIn('${state.loading ? "Katalog wird geladen …" : "Discovery/Katalog"}', self.source)


if __name__ == "__main__":
    unittest.main()
