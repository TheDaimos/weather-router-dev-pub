"""Offline regression of UTC-backed event relevance and feed recency.

No HA/network/private sources. Events are synthetic; permissions are outside
this pure helper and remain owned by the existing Consumer API.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import importlib
import sys
import types
import unittest

PKG = "wr_p7010_event_window_test"
BASE = Path(__file__).resolve().parents[1] / "custom_components/weather_router"
if PKG not in sys.modules:
    package = types.ModuleType(PKG)
    package.__path__ = [str(BASE)]
    sys.modules[PKG] = package
policy = importlib.import_module(PKG + ".consumer_event_time_policy")
NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def request(start="2026-10-15T00:00:00Z", end="2026-10-16T11:59:00Z",
            ongoing=True, age=3600):
    return {"mode": "events_intersecting_window",
            "window": {"start": start, "end": end},
            "include_ongoing": ongoing, "max_feed_update_age_seconds": age}


def validate(class_id="weather.warning.official", typ="hazard_feed", **options):
    return policy.validate_event_time(
        request(**options), public_id=class_id,
        resource_types={typ}, now=NOW)


def events_filtered(events, contract=None, published="2026-10-16T11:40:00Z"):
    return policy.filter_event_payload(
        {"events": events}, time=contract or validate(),
        provider_result={"last_updated_at": published} if published is not None else {},
        now=NOW)


class EventWindowTests(unittest.TestCase):
    def test_offset_equivalence_and_bounded_window(self):
        a = validate(start="2026-10-15T00:00:00Z")
        b = validate(start="2026-10-15T02:00:00+02:00")
        self.assertEqual(a["window"], b["window"])
        with self.assertRaisesRegex(ValueError, "event_window_too_large"):
            validate(start="2026-08-01T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "future_event_window"):
            validate(end="2026-10-17T00:00:00Z")
        with self.assertRaises(ValueError):
            validate(start="2026-10-15T00:00:00")

    def test_warning_longer_than_15_minutes_is_still_active(self):
        result = events_filtered([{
            "id": "official", "effective": "2026-10-15T08:00:00Z",
            "expires": "2026-10-17T08:00:00Z", "status": "active"}])
        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["events"][0]["temporal_status"], "ongoing")
        self.assertEqual(result["event_time_policy"]["feed_status"], "fresh")

    def test_ended_warning_outside_window_excluded(self):
        result = events_filtered([
            {"id": "ended", "effective": "2026-10-10T00:00:00Z",
             "ends": "2026-10-14T23:00:00Z", "status": "ended"}])
        self.assertEqual(result["events"], [])
        self.assertEqual(result["event_time_policy"]["rejected_counts"]["ended_before_window"], 1)

    def test_active_volcano_old_start_requires_recent_verified_update(self):
        contract = validate("natural_hazards.volcano.activity",
                            start="2026-10-01T00:00:00Z", age=86400)
        eruption = {"id": "eruption", "started_at": "2026-04-12T12:00:00Z",
                    "status": "active",
                    "last_updated_at": "2026-10-16T11:00:00Z"}
        result = events_filtered([eruption], contract)
        self.assertEqual(result["events"][0]["temporal_status"], "ongoing")
        missing_update = dict(eruption)
        missing_update.pop("last_updated_at")
        blocked = events_filtered([missing_update], contract, published=None)
        self.assertEqual(blocked["events"], [])
        self.assertEqual(blocked["event_time_policy"]["rejected_counts"]["unverified_ongoing"], 1)

    def test_fresh_feed_does_not_extend_unverified_open_ended_event(self):
        # Receiving a fresh feed cannot reactivate an old volcano, indefinite
        # warning, or already-ended event without a fresh event lifecycle update.
        contract = validate("natural_hazards.volcano.activity",
                            start="2026-10-01T00:00:00Z", age=86400)
        eruption = {"id":"outdated", "started_at":"2026-04-12T12:00:00Z",
                    "status":"active"}
        result = events_filtered([eruption], contract,
                                 published="2026-10-16T11:59:00Z")
        self.assertEqual(result["events"], [])
        self.assertEqual(result["event_time_policy"]["feed_status"], "fresh")
        self.assertEqual(result["event_time_policy"]["rejected_counts"]
                         ["unverified_ongoing"], 1)

    def test_closed_warning_cannot_remain_ongoing_with_future_expiry(self):
        result = events_filtered([{
            "id":"withdrawn", "effective":"2026-10-15T08:00:00Z",
            "expires":"2026-10-17T08:00:00Z", "status":"withdrawn"}])
        self.assertEqual(result["events"], [])
        self.assertEqual(result["event_time_policy"]["rejected_counts"]
                         ["closed_status_conflict"], 1)

    def test_explicit_event_update_distinct_from_feed_update(self):
        contract = validate("natural_hazards.volcano.activity",
                            start="2026-10-01T00:00:00Z", age=86400)
        event = {"id":"long-running", "started_at":"2026-04-12T12:00:00Z",
                 "status":"active",
                 "last_updated_at":"2026-10-16T11:00:00+00:00"}
        result = events_filtered([event], contract,
                                 published="2026-10-10T11:00:00Z")
        self.assertEqual(result["events"][0]["temporal_status"], "ongoing")
        self.assertEqual(result["event_time_policy"]["feed_status"], "stale")

    def test_official_usgs_elevated_notice_not_equated_with_eruption(self):
        contract = validate("natural_hazards.volcano.activity",
                            start="2026-10-01T00:00:00Z", age=86400)
        notice = {
            "id": "usgs-hans", "effective": "2026-10-15T11:00:00Z",
            "status": "actual", "lifecycle_status": "ongoing",
            "last_updated_at": "2026-10-16T11:00:00Z",
            "volcano_semantics": {
                "semantic_class": "official_volcano_status_event",
                "volcano_alert_level": "WATCH"},
        }
        result = events_filtered([notice], contract, published=None)
        self.assertEqual(result["events"][0]["temporal_status"], "ongoing")
        self.assertEqual(result["events"][0]["volcano_semantics"]["volcano_alert_level"],
                         "WATCH")
        weekly = {
            "id": "smithsonian-report", "effective": "2026-10-15T08:00:00Z",
            "status": "actual", "volcano_semantics": {
                "semantic_class": "weekly_volcanic_activity_report_event"},
        }
        historical = events_filtered([weekly], contract, published=None)
        self.assertEqual(historical["events"][0]["temporal_status"], "historical_event")
        self.assertEqual(events_filtered([{
            **weekly, "effective": "2026-09-01T08:00:00Z"}],
            contract, published=None)["event_count"], 0)

    def test_quake_and_sighting_are_historical_not_live_location(self):
        quake = validate("natural_hazards.earthquake.events",
                         start="2026-10-01T00:00:00Z", age=3600)
        quake_result = events_filtered([
            {"id": "quake", "observed_at": "2026-10-05T12:00:00Z",
             "status": "active"}], quake)
        self.assertEqual(quake_result["events"][0]["temporal_status"], "historical_event")
        # Wildlife sightings are not yet registered. Demonstrate the
        # historical-only semantics without enabling an unregistered intent.
        with self.assertRaisesRegex(ValueError, "unsupported_event_time_capability"):
            validate("biology.jellyfish.sightings", "event_feed",
                     start="2026-10-01T00:00:00Z", age=3600)
        sighting = dict(quake, **{"class": "historical_sighting"})
        sight = events_filtered([
            {"id": "jellyfish", "observed_at": "2026-10-05T12:00:00Z",
             "status": "active"}], sighting)
        self.assertEqual(sight["events"][0]["temporal_status"], "historical_observation")
        self.assertEqual(events_filtered([
            {"id": "old", "observed_at": "2026-09-01T12:00:00Z"}], sighting)["event_count"], 0)

    def test_point_event_uses_occurrence_not_later_bulletin_time(self):
        contract = validate("natural_hazards.earthquake.events",
                            start="2026-10-15T00:00:00Z", age=3600)
        quake = {"id":"old-quake", "occurred_at":"2026-09-01T08:00:00Z",
                 "effective":"2026-10-16T11:00:00Z", "status":"active"}
        result = events_filtered([quake], contract)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["event_time_policy"]["rejected_counts"]
                         ["before_window"], 1)

    def test_future_point_event_never_marked_observed(self):
        contract = validate("natural_hazards.earthquake.events",
                            start="2026-10-15T00:00:00Z",
                            end="2026-10-16T12:03:00Z", age=3600)
        quake = {"id":"future-quake", "occurred_at":"2026-10-16T12:02:00Z"}
        result = events_filtered([quake], contract)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["event_time_policy"]["rejected_counts"]
                         ["future_observation"], 1)

    def test_scheduled_warning_not_falsely_active(self):
        contract = validate(end="2026-10-16T12:03:00Z")
        warning = {"id":"tomorrow-soon",
                   "effective":"2026-10-16T12:02:00Z",
                   "expires":"2026-10-16T19:00:00Z",
                   "status":"actual"}
        result = events_filtered([warning], contract)
        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["events"][0]["temporal_status"], "scheduled")

    def test_stale_feed_is_labelled_not_silently_made_fresh(self):
        result = events_filtered([
            {"id": "official", "effective": "2026-10-15T08:00:00Z",
             "expires": "2026-10-17T08:00:00Z", "status": "active"}],
            published="2026-10-16T06:00:00Z")
        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["event_time_policy"]["feed_status"], "stale")
        self.assertEqual(result["event_time_policy"]["feed_age_seconds"], 21600)
        unknown = events_filtered([
            {"id": "official", "effective": "2026-10-15T08:00:00Z",
             "expires": "2026-10-17T08:00:00Z", "status": "active"}], published=None)
        self.assertEqual(unknown["event_time_policy"]["feed_status"], "unknown")

    def test_all_registered_feed_capabilities_have_explicit_time_policy(self):
        import json
        mapping = json.loads((BASE / "consumer_capability_map.json").read_text(encoding="utf-8"))
        registered = {
            id: entry["resource_types"][0]
            for id, entry in mapping["public_capabilities"].items()
            if len(entry.get("resource_types", [])) == 1
            and entry["resource_types"][0] in ("hazard_feed", "event_feed")
        }
        declared = policy._declared_policies()
        self.assertEqual(set(declared), set(registered))
        for id, resource in registered.items():
            self.assertEqual(declared[id]["resource_type"], resource)
            self.assertIn(declared[id]["time_class"], policy._CLASSES)

    def test_bounded_event_pages_are_separate_from_age(self):
        events = [{"id":str(i), "observed_at":"2026-10-16T10:00:00Z"}
                  for i in range(305)]
        base = validate("natural_hazards.earthquake.events",
                        age=3600, start="2026-10-01T00:00:00Z")
        pages = []
        for p in range(1, 5):
            contract = {**base, "page": p, "page_size": 100}
            result = events_filtered(events, contract)
            pages.append(result)
        self.assertEqual([r["event_count"] for r in pages], [100, 100, 100, 5])
        self.assertEqual([r["event_time_policy"]["has_more"] for r in pages],
                         [True, True, True, False])
        ids = [e["id"] for page in pages for e in page["events"]]
        self.assertEqual(ids, [str(i) for i in range(305)])
        self.assertTrue(all(p["event_time_policy"]["rejection_counts_scope"]
                            == "scanned_prefix" for p in pages))

    def test_event_page_and_page_size_are_hard_bounded(self):
        for key, value in (("page", 0), ("page", 6), ("page", True),
                           ("page_size", 0), ("page_size", 201),
                           ("page_size", False)):
            req = request()
            req[key] = value
            with self.assertRaises(ValueError):
                policy.validate_event_time(
                    req, public_id="weather.warning.official",
                    resource_types={"hazard_feed"}, now=NOW)

    def test_limits_and_wrong_resource_fail_closed(self):
        with self.assertRaises(ValueError):
            policy.validate_event_time(request(), public_id="weather.precipitation.layer",
                                       resource_types={"raster_tile"}, now=NOW)
        with self.assertRaises(ValueError):
            policy.validate_event_time(request(), public_id="weather.warning.official",
                                       resource_types={"hazard_feed", "event_feed"}, now=NOW)
        too_many = [{"id": str(i), "observed_at": "2026-10-16T10:00:00Z"}
                    for i in range(350)]
        p = validate("natural_hazards.earthquake.events", age=3600)
        result = events_filtered(too_many, p)
        self.assertEqual(result["event_count"], 200)
        self.assertTrue(result["event_time_policy"]["truncated"])


if __name__ == "__main__":
    unittest.main()
