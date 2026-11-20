"""Regression tests for OPERA service defaults; no Home Assistant instance required."""
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components/weather_router/opera_config.py"
SPEC = importlib.util.spec_from_file_location("wr_opera_config_under_test", MODULE_PATH)
opera_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(opera_config)


class OperaDefaultsTests(unittest.TestCase):
    def test_new_install_enables_all_three_service_preferences(self):
        settings = opera_config.read_config({})
        self.assertEqual(settings["services"], {"RATE": True, "DBZH": True, "ACRR": True})

    def test_new_install_uses_last_tested_freshness_policy(self):
        settings = opera_config.read_config({})
        self.assertEqual(settings["max_age_seconds"], 1650)
        self.assertEqual(settings["stale_after_seconds"], 1651)
        self.assertEqual(settings["max_stale_age_seconds"], 3600)

    def test_saved_freshness_choices_are_preserved(self):
        settings = opera_config.read_config({
            "opera_max_age_seconds": 1500, "opera_stale_after_seconds": 1500,
        })
        self.assertEqual(settings["max_age_seconds"], 1500)
        self.assertEqual(settings["stale_after_seconds"], 1500)

    def test_existing_explicitly_disabled_choices_are_preserved(self):
        settings = opera_config.read_config({
            "opera_services": {"RATE": False, "DBZH": True, "ACRR": False}
        })
        self.assertEqual(settings["services"], {"RATE": False, "DBZH": True, "ACRR": False})

    def test_partial_legacy_service_selection_keeps_explicit_choice(self):
        settings = opera_config.read_config({"opera_services": {"RATE": False}})
        self.assertEqual(settings["services"], {"RATE": False, "DBZH": True, "ACRR": True})

    def test_new_defaults_do_not_grant_scientific_approval(self):
        settings = opera_config.read_config({})
        self.assertEqual(set(settings["scientific_status"].values()), {"UNVERIFIED"})
        self.assertFalse(settings["serve_stale"])


if __name__ == "__main__":
    unittest.main()
