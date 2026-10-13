"""Regression test for the P5-SPACE-60 diagnostics readiness hotfix."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "custom_components" / "weather_router" / "routing_diagnostic_core.py"
CONST = ROOT / "custom_components" / "weather_router" / "const.py"
LAB = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"


from wr_public_version_contract import assert_current_version_surfaces

class P5SpaceDiagnosticsHotfixTest(unittest.TestCase):
    """Keep OVATION observation and forecast times visible in diagnostics."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.core = CORE.read_text(encoding="utf-8")
        cls.const = CONST.read_text(encoding="utf-8")
        cls.lab = LAB.read_text(encoding="utf-8")
        cls.loader = LOADER.read_text(encoding="utf-8")

    def test_data_file_summary_exposes_all_three_time_fields(self) -> None:
        self.assertIn('"data_time": payload.get("data_time")', self.core)
        self.assertIn('"valid_time": payload.get("valid_time")', self.core)
        self.assertIn(
            '"forecast_reference_time": payload.get("forecast_reference_time")',
            self.core,
        )

    def test_build_surfaces_are_010136_loader139(self) -> None:
        assert_current_version_surfaces(self, self.const, self.lab, self.loader)


if __name__ == "__main__":
    unittest.main()
