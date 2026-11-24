"""Standalone lunar contract tests; run with astronomy-engine==2.1.19."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

spec = importlib.util.spec_from_file_location("moon_engine", Path(__file__).resolve().parents[1] / "custom_components/weather_router/moon_engine.py")
moon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(moon)


class MoonTest(unittest.TestCase):
    def test_invalid_inputs(self):
        for lat, lon in [(91, 0), (0, 181), (float("nan"), 0)]:
            with self.assertRaises(ValueError):
                moon.calculate_moon(lat, lon, datetime(2024, 4, 8, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            moon.calculate_moon(0, 0, datetime(2024, 4, 8))

    def test_eclipse_new_moon_and_locations(self):
        at = datetime(2024, 4, 8, 18, 21, tzinfo=timezone.utc)
        a = moon.calculate_moon(52.52, 13.405, at, "Europe/Berlin")
        b = moon.calculate_moon(-33.87, 151.21, at, "Australia/Sydney")
        self.assertEqual(a["phase"], "new_moon")
        self.assertLess(a["illumination_percent"], 1)
        self.assertEqual(a["phase_angle_deg"], b["phase_angle_deg"])
        self.assertEqual(a["next_major_phase"]["utc"], b["next_major_phase"]["utc"])
        self.assertNotEqual(a["moonrise"], b["moonrise"])

    def test_full_moon_reference(self):
        at = datetime(2024, 3, 25, 7, 0, tzinfo=timezone.utc)
        data = moon.calculate_moon(0, 0, at)
        self.assertEqual(data["phase"], "full_moon")
        self.assertGreater(data["illumination_percent"], 99)
        self.assertTrue(13 < data["moon_age_days"] < 17)

    def test_geographic_timezones(self):
        for lat, lon, expected in [(52.52, 13.405, "Europe/Berlin"),
                                   (40.7128, -74.006, "America/New_York"),
                                   (-33.87, 151.21, "Australia/Sydney")]:
            self.assertEqual(moon.resolve_timezone(lat, lon), expected)

    def test_poles_and_dst(self):
        at = datetime(2024, 3, 31, 12, tzinfo=timezone.utc)
        for lat, lon, zone in [(89.9, 0, "UTC"), (-89.9, 180, "Pacific/Auckland"),
                               (52.52, 13.405, "Europe/Berlin")]:
            data = moon.calculate_moon(lat, lon, at, zone)
            for key in ("moonrise", "moonset"):
                if data[key] is not None:
                    self.assertEqual(data[key]["local"][:10], data["local_date"])
            self.assertGreaterEqual(data["cycle_fraction"], 0)
            self.assertLessEqual(data["cycle_fraction"], 1)

    def test_dst_civil_day_boundaries(self):
        for day, hours in [("2024-03-31", 23), ("2024-10-27", 25)]:
            at = datetime.fromisoformat(day + "T12:00:00+00:00")
            zone = ZoneInfo("Europe/Berlin")
            start = datetime.combine(at.date(), datetime.min.time(), zone).astimezone(timezone.utc)
            end = datetime.combine(at.date() + timedelta(days=1), datetime.min.time(), zone).astimezone(timezone.utc)
            self.assertEqual((end-start).total_seconds(), hours*3600)
            data = moon.calculate_moon(52.52, 13.405, at, "Europe/Berlin")
            for key in ("moonrise", "moonset"):
                if data[key]:
                    event = datetime.fromisoformat(data[key]["utc"])
                    self.assertTrue(start <= event < end)
                    self.assertEqual(data[key]["local"], event.astimezone(zone).isoformat())

    def test_local_date_crosses_utc_date_line(self):
        at = datetime(2024, 4, 8, 23, 30, tzinfo=timezone.utc)
        east = moon.calculate_moon(-33.87, 151.21, at)
        west = moon.calculate_moon(40.7128, -74.006, at)
        self.assertEqual(east["local_date"], "2024-04-09")
        self.assertEqual(west["local_date"], "2024-04-08")
        self.assertEqual(east["timezone"], "Australia/Sydney")
        self.assertEqual(west["timezone"], "America/New_York")

    def test_timezone_utc_fallback_and_override(self):
        with patch.object(moon, "_timezone_finder", side_effect=ImportError):
            self.assertEqual(moon.resolve_timezone(52.52, 13.405), "UTC")
            data = moon.calculate_moon(52.52, 13.405, datetime(2024, 4, 8, tzinfo=timezone.utc))
            self.assertEqual(data["timezone"], "UTC")
            override = moon.calculate_moon(52.52, 13.405, datetime(2024, 4, 8, tzinfo=timezone.utc), "America/New_York")
            self.assertEqual(override["timezone"], "America/New_York")

    def test_invalid_year_and_zone(self):
        for year in (1900, 2100):
            with self.assertRaises(ValueError):
                moon.calculate_moon(0, 0, datetime(year, 1, 1, tzinfo=timezone.utc), "UTC")
        with self.assertRaises(ZoneInfoNotFoundError):
            moon.calculate_moon(0, 0, datetime(2024, 1, 1, tzinfo=timezone.utc), "Invalid/Zone")

    def test_all_phase_classes_and_cycle_consistency(self):
        phases = set()
        for day in range(1, 31):
            at = datetime(2024, 4, day, 12, tzinfo=timezone.utc)
            data = moon.calculate_moon(52.52, 13.405, at, "Europe/Berlin")
            phases.add(data["phase"])
            self.assertTrue(29 < data["cycle_days"] < 30)
            self.assertTrue(0 <= data["moon_age_days"] < data["cycle_days"])
            self.assertAlmostEqual(data["cycle_fraction"], data["moon_age_days"]/data["cycle_days"])
            self.assertTrue(0 <= data["illumination_percent"] <= 100)
            self.assertGreater(datetime.fromisoformat(data["next_major_phase"]["utc"]), at)
            self.assertIn(data["next_major_phase"]["phase"], moon.PHASES[::2])
        self.assertEqual(phases, set(moon.PHASES))

    def test_near_conjunction_and_geographic_isolation(self):
        for stamp in ("2024-04-08T18:20:00+00:00", "2024-04-08T18:22:00+00:00"):
            at = datetime.fromisoformat(stamp)
            data = moon.calculate_moon(0, 0, at, "UTC")
            self.assertTrue(0 <= data["moon_age_days"] < data["cycle_days"])
            self.assertLess(data["illumination_percent"], .1)
        # Polar no-rise/set is a valid result, not a provider error.
        polar = moon.calculate_moon(89.9, 0, datetime(2024, 3, 31, 12, tzinfo=timezone.utc), "UTC")
        self.assertIsNone(polar["moonrise"])
        self.assertIsNone(polar["moonset"])

if __name__ == "__main__":
    unittest.main()
