"""Regression coverage for P5-SPACE-60 astronomy phase fail-closed hotfix."""

from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = ROOT / "custom_components" / "weather_router" / "providers" / "met_norway_astronomy.py"
CONST = ROOT / "custom_components" / "weather_router" / "const.py"
LAB = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab.js"
LOADER = ROOT / "custom_components" / "weather_router" / "frontend" / "weather-router-lab-dev-loader.js"


from wr_public_version_contract import assert_current_version_surfaces

class P5SpaceAstronomyPhaseHotfixTest(unittest.TestCase):
    """Keep missing moon phase data from being exported as a ready null value."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.provider = PROVIDER.read_text(encoding="utf-8")
        cls.const = CONST.read_text(encoding="utf-8")
        cls.lab = LAB.read_text(encoding="utf-8")
        cls.loader = LOADER.read_text(encoding="utf-8")

    def test_phase_dependent_capabilities_fail_closed_without_phase(self) -> None:
        for capability in (
            "moon_phase_angle",
            "moon_phase_name",
            "moon_illumination",
            "moon_age_days",
        ):
            self.assertIn(capability, self.provider)
        self.assertIn('if phase is None and any(item in phase_required for item in requested):', self.provider)
        self.assertIn('"available": False', self.provider)
        self.assertIn('"unavailable_code": "temporarily_unavailable"', self.provider)
        self.assertIn("keinen nutzbaren Mondphasenwinkel", self.provider)

    def test_version_surfaces_are_010137_loader140(self) -> None:
        assert_current_version_surfaces(self, self.const, self.lab, self.loader)


if __name__ == "__main__":
    unittest.main()
