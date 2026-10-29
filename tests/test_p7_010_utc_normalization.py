"""UTC and provider time regression cases, offline and provider-neutral."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
spec = importlib.util.spec_from_file_location("wr_utc_normalization", BASE / "time_normalization.py")
assert spec and spec.loader
times = importlib.util.module_from_spec(spec)
spec.loader.exec_module(times)


class UtcNormalizationTests(unittest.TestCase):
    def test_offset_equivalence_and_naive_rejection(self):
        for raw in ("2026-10-16T12:00:00Z", "2026-10-16T14:00:00+02:00",
                    "2026-10-16T06:00:00-06:00"):
            self.assertEqual(times.iso_instant(raw), "2026-10-16T12:00:00Z")
        for invalid in ("2026-10-16T12:00:00", "2026-10-16", "current",
                        "", "tomorrow", "not-a-time"):
            self.assertIsNone(times.iso_instant(invalid))

    def test_epoch_units_explicit(self):
        self.assertEqual(times.epoch_instant(1792152000, unit="seconds"),
                         "2026-10-16T12:00:00Z")
        self.assertEqual(times.epoch_instant(1792152000000, unit="milliseconds"),
                         "2026-10-16T12:00:00Z")
        with self.assertRaises(ValueError):
            times.epoch_instant(1792152000, unit="unknown")
        for value in (float("nan"), float("inf"), True, "1792152000"):
            self.assertIsNone(times.epoch_instant(value, unit="seconds"))

    def test_iana_dst_gap_and_fold_fail_closed(self):
        self.assertEqual(
            times.provider_local_instant("2026-10-16T14:00:00", iana_zone="Europe/Berlin"),
            "2026-10-16T12:00:00Z")
        self.assertIsNone(times.provider_local_instant(
            "2026-03-29T02:30:00", iana_zone="Europe/Berlin"))
        self.assertIsNone(times.provider_local_instant(
            "2026-10-25T02:30:00", iana_zone="Europe/Berlin"))
        self.assertEqual(times.provider_local_instant(
            "2026-01-16T14:00:00", iana_zone="Europe/Berlin"),
            "2026-01-16T13:00:00Z")
        self.assertIsNone(times.provider_local_instant(
            "2026-10-16T14:00:00", iana_zone="Unknown/Zone"))

    def test_rss_and_wms_interval(self):
        self.assertEqual(times.rss_instant("Fri, 16 Oct 2026 14:00:00 +0200"),
                         "2026-10-16T12:00:00Z")
        self.assertIsNone(times.rss_instant("Fri, 16 Oct 2026 14:00:00"))
        self.assertIsNone(times.rss_instant("unknown"))
        self.assertEqual(times.wms_time_values(
            "2026-10-16T10:00:00Z/2026-10-16T11:00:00Z/PT30M"),
            ["2026-10-16T10:00:00Z", "2026-10-16T10:30:00Z",
             "2026-10-16T11:00:00Z"])
        self.assertEqual(times.wms_time_values("2026-10-16/current/PT30M"), [])
        self.assertEqual(times.wms_time_values("2026-10-16"), [])

    def test_local_calendar_day_is_interval_not_observation(self):
        self.assertEqual(times.calendar_day_interval(
            "2026-03-29", iana_zone="Europe/Berlin"),
            ("2026-03-28T23:00:00Z", "2026-03-29T22:00:00Z"))
        self.assertEqual(times.calendar_day_interval(
            "2026-10-25", iana_zone="Europe/Berlin"),
            ("2026-10-24T22:00:00Z", "2026-10-25T23:00:00Z"))


if __name__ == "__main__":
    unittest.main()
