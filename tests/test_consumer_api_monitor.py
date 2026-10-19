"""Dependency-free API monitor privacy and memory contract tests."""
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "custom_components/weather_router/consumer_api_monitor.py"
spec = importlib.util.spec_from_file_location("monitor", path)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class TestApiMonitor(unittest.TestCase):
    def test_default_disabled_and_no_entries(self):
        m = monitor.ConsumerApiMonitor()
        self.assertIsNone(m.begin(api_version="V1", command="resolve", message={"token":"x"}))
        self.assertEqual(m.query()["entries"], [])

    def test_secret_and_location_redaction(self):
        m = monitor.ConsumerApiMonitor()
        m.configure(enabled=True)
        t = m.begin(api_version="V2", command="resolve_mosaic",
                    message={"consumer_id":"gewitterradar", "capability":"weather.radar.precipitation",
                             "context":{"west":9, "north":52}, "auth_token":"private",
                             "correlation_id":"abc"})
        m.finish(t, result="success", response={"authorization":"secret", "data":"large",
                                               "latitude":53}, providers=["provider_x"])
        row = m.query(consumer="gewitterradar", api_version="V2")["entries"][0]
        self.assertEqual(row["request"]["auth_token"], "[redacted]")
        self.assertEqual(row["request"]["context"]["west"], "[location-redacted]")
        self.assertEqual(row["response"]["authorization"], "[redacted]")
        self.assertEqual(row["response"]["data"], "[payload-omitted]")
        self.assertEqual(row["correlation_id"], "abc")
        self.assertFalse(row["consumer_trusted"])

    def test_filter_and_bound(self):
        m = monitor.ConsumerApiMonitor(max_records=2, max_bytes=4096)
        m.configure(enabled=True)
        for k in range(5):
            t=m.begin(api_version="V1", command="resolve", message={"capability":f"w{k}"})
            m.finish(t,result="no_data")
        self.assertEqual(len(m.query()["entries"]),2)
        self.assertEqual(m.query(capability="w1")["record_count"],0)
        self.assertEqual(m.query(result="no_data")["record_count"],2)

    def test_proxy_preserves_responses(self):
        class Dummy:
            user = type("U", (), {"id": "admin-1"})()
            def __init__(self):
                self.output = None
            def send_result(self, req, result):
                self.output = ("result", req, result)
            def send_error(self, req, code, detail):
                self.output = ("error", req, code)
        m = monitor.ConsumerApiMonitor()
        m.configure(enabled=True)
        target = Dummy()
        proxy = monitor.MonitoredConnection(target, m,
                                            {"id": 5, "consumer_id": "aurora_borealis",
                                             "capability": "weather.radar.precipitation", "type": "resolve"},
                                            "V1")
        proxy.send_result(5, {"status": "ready", "provider_id": "source-a"})
        self.assertEqual(target.output[0], "result")
        self.assertEqual(m.query(consumer="aurora_borealis")["record_count"], 1)
        proxy.send_result(5, {"status": "ready"})
        self.assertEqual(m.query()["record_count"], 1)

    def test_redact_signed_url_and_nonfinite(self):
        m = monitor.ConsumerApiMonitor()
        m.configure(enabled=True)
        ticket=m.begin(api_version="V2",command="resolve_mosaic",message={})
        m.finish(ticket,result="success",response={"url":"https://example.test/?token=SECRET",
                                                  "rate":float("nan")})
        row=m.query()["entries"][0]
        self.assertEqual(row["response"]["url"], "[sensitive-text-omitted]")
        self.assertEqual(row["response"]["rate"], "[non-finite-number]")

    def test_oversize_keeps_routing_decision(self):
        m = monitor.ConsumerApiMonitor()
        m.configure(enabled=True)
        token = m.begin(api_version="V1", command="resolve",
                        message={"capability": "weather.precipitation.layer",
                                 "context": {"payload": "x" * 50000}})
        m.finish(token, result="success",
                 response={"status": "success", **{f"detail_{i}": "x" * 300 for i in range(60)}},
                 routing={"decision": {"selected_provider": "nasa_gibs",
                                        "reason_code": "best_coverage",
                                        "status": "selected"},
                          "candidates": [{"provider_id": "dwd", "result": "rejected"}] * 500})
        row = m.query()["entries"][0]
        self.assertTrue(row.get("truncated"))
        self.assertEqual(row["routing"]["decision"]["selected_provider"], "nasa_gibs")
        self.assertIn("nasa_gibs", row["providers"])
        self.assertEqual(row["result"], "success")
        self.assertLessEqual(len(__import__("json").dumps(row).encode()), 8192)

    def test_oversized_v2_keeps_structured_rejection_causes(self):
        m = monitor.ConsumerApiMonitor()
        m.configure(enabled=True)
        token = m.begin(api_version="V2", command="weather_router/consumer/resolve_mosaic",
                        message={"consumer_id":"gewitterradar",
                                 "correlation_id":"abc-v2-age",
                                 "capability":"weather.precipitation.layer"})
        m.finish(token, result="no_data",
                 response={"status":"unavailable",
                           **{f"large_{i}":"data" * 100 for i in range(70)}},
                 routing={"contacts_selected":4,
                          "sources_eligible":1,
                          "selected_sources":["nasa_gibs/satellite_precipitation_imerg_30min"],
                          "final_layers_count":0,
                          "source_rejections":[{"source_id":"nasa_gibs/satellite_precipitation_imerg_30min",
                                                "reason":"no_fresh_verified_frame"}]})
        row = m.query()["entries"][0]
        self.assertEqual(row["correlation_id"], "abc-v2-age")
        self.assertEqual(row["routing"]["final_layers_count"], 0)
        self.assertEqual(row["routing"]["source_rejections"][0]["reason"],
                         "no_fresh_verified_frame")
        self.assertLessEqual(len(__import__("json").dumps(row).encode()),8192)

    def test_oversized_v2_keeps_coverage_preflight_and_12h_opt_in(self):
        m = monitor.ConsumerApiMonitor()
        m.configure(enabled=True)
        token = m.begin(api_version="V2",
                        command="weather_router/consumer/resolve_mosaic",
                        message={"consumer_id": "gewitterradar",
                                 "correlation_id": "p7-dwd-timeout",
                                 "time": {"mode": "latest_coherent",
                                          "max_data_age_seconds": 900,
                                          "max_time_delta_seconds": 180,
                                          "max_background_age_seconds": 43200}})
        m.finish(token, result="success",
                 response={"status": "partial",
                           **{f"noise_{i}": "x" * 400 for i in range(50)}},
                 routing={"coverage_preflight": [
                     {"source_id": "dwd/radar_precipitation",
                      "result": "coverage_timeout", "duration_ms": 6001.4,
                      "cache_hit": False},
                     {"source_id": "nasa_gibs/satellite_precipitation_imerg_30min",
                      "result": "coverage_accepted", "duration_ms": 33.1,
                      "cache_hit": True}],
                          "contacts_selected": 2, "sources_eligible": 1,
                          "final_layers_count": 1})
        row = m.query(correlation_id="p7-dwd-timeout")["entries"][0]
        self.assertTrue(row.get("truncated"))
        self.assertEqual(row["routing"]["coverage_preflight"][0]["result"],
                         "coverage_timeout")
        self.assertEqual(row["request"]["time"]["max_background_age_seconds"], 43200)
        self.assertLessEqual(len(__import__("json").dumps(row).encode()), 8192)

    def test_truncated_v2_retains_source_order_and_machine_reasons(self):
        m = monitor.ConsumerApiMonitor()
        m.configure(enabled=True)
        layers = [
            {
                "source_id": "nasa_gibs/imer",
                "freshness_class": "older_background",
                "composition": {"draw_order": 0, "role": "background",
                                "routing_score": [2, 0, 1]},
                "times": {"valid_at": "2026-10-19T04:00:00Z",
                          "age_seconds": 27000},
            },
            {
                "source_id": "dwd/checked",
                "freshness_class": "current",
                "composition": {"draw_order": 1, "role": "overlay",
                                "routing_score": [0, 0, 0]},
                "times": {"valid_at": "2026-10-19T07:00:00Z",
                          "age_seconds": 90},
            },
        ]
        outcomes = [
            {"source_id": "nasa_gibs/imer", "result": "selected"},
            {"source_id": "dwd/checked", "result": "selected"},
            {"source_id": "dwd/icon", "result": "source_stale"},
        ]
        t = m.begin(api_version="V2", command="resolve_mosaic",
                    message={"consumer_id": "gewitterradar",
                             "correlation_id": "rf03-monitor"})
        m.finish(t, result="success", response={
            "contract_version": 2, "status": "partial",
            "layer_order": "background_to_foreground",
            "layers": layers, "source_outcomes": outcomes,
            **{f"large_{i}": "x" * 420 for i in range(45)},
        }, routing={
            "delivered_sources": ["nasa_gibs/imer", "dwd/checked"],
            "source_outcomes": outcomes,
            "layer_order": "background_to_foreground",
            "final_layers_count": 2,
        })
        row = m.query(correlation_id="rf03-monitor")["entries"][0]
        self.assertTrue(row["truncated"])
        self.assertEqual(row["response"]["layer_order"],
                         "background_to_foreground")
        self.assertEqual(
            [layer["source_id"] for layer in row["response"]["layers"]],
            ["nasa_gibs/imer", "dwd/checked"])
        self.assertEqual(row["response"]["layers"][-1]["composition"]["draw_order"], 1)
        self.assertEqual(row["routing"]["source_outcomes"][-1]["result"],
                         "source_stale")
        self.assertEqual(row["routing"]["delivered_sources"][-1], "dwd/checked")

    def test_v1_time_contract_error_survives_compaction(self):
        m = monitor.ConsumerApiMonitor()
        m.configure(enabled=True)
        t = m.begin(api_version="V1", command="resolve",
                    message={"consumer_id": "gewitterradar",
                             "correlation_id": "p7-utc-failure"})
        m.finish(t, result="success", response={
            "status": "ready",
            "resource": {"type": "raster_tile", "payload": {
                "time_normalization_error": "unverified_source_time_contract",
                "tile_url": "https://example.invalid/secret-path",
            }},
            **{f"large_{i}": "x" * 300 for i in range(70)}
        })
        row = m.query(correlation_id="p7-utc-failure")["entries"][0]
        self.assertEqual(row["source_time_error"], "unverified_source_time_contract")
        self.assertLessEqual(len(__import__("json").dumps(row).encode()), 8192)

    def test_event_window_compaction_keeps_separate_feed_age_and_reasons(self):
        m = monitor.ConsumerApiMonitor()
        m.configure(enabled=True)
        ticket = m.begin(
            api_version="V1", command="weather_router/consumer/resolve",
            message={"consumer_id": "gewitterradar",
                     "correlation_id": "event-window-123",
                     "capability": "weather.warning.official",
                     "time": {
                         "mode": "events_intersecting_window",
                         "window": {"start": "2026-10-01T00:00:00Z",
                                    "end": "2026-10-16T12:00:00Z"},
                         "include_ongoing": True,
                         "max_feed_update_age_seconds": 3600,
                         "page": 2, "page_size": 50}})
        policy_data = {
            "class": "official_warning", "feed_status": "stale",
            "feed_age_seconds": 8000,
            "feed_updated_at": "2026-10-16T09:46:40Z",
            "max_feed_update_age_seconds": 3600,
            "page": 2, "page_size": 50, "max_pages": 5,
            "has_more": True, "rejection_counts_scope": "scanned_prefix",
            "rejected_counts": {"ended_before_window": 3},
            "window": {"start": "2026-10-01T00:00:00Z",
                       "end": "2026-10-16T12:00:00Z"},
        }
        m.finish(ticket, result="success", response={
            "status": "ready",
            **{f"large_{i}": "x" * 300 for i in range(45)},
            "resource": {
                "type": "hazard_feed", "payload": {
                    "event_time_policy": policy_data,
                    "events": [{"description": "x" * 5000} for _ in range(30)],
                }}},
            routing={"candidates": [{"provider_id": "dwd",
                                     "result": "selected"}] * 100})
        row = m.query(correlation_id="event-window-123")["entries"][0]
        self.assertEqual(row["event_time_policy"]["feed_status"], "stale")
        self.assertEqual(row["event_time_policy"]["rejected_counts"]["ended_before_window"], 3)
        self.assertEqual(row["request"]["time"]["mode"], "events_intersecting_window")
        self.assertEqual(row["request"]["time"]["page"], 2)
        self.assertEqual(row["event_time_policy"]["page_size"], 50)
        self.assertTrue(row["event_time_policy"]["has_more"])
        self.assertLessEqual(len(__import__("json").dumps(row).encode()), 8192)

    def test_stop_removes_data(self):
        m=monitor.ConsumerApiMonitor()
        m.configure(enabled=True)
        t=m.begin(api_version="V1",command="resolve",message={})
        m.finish(t,result="error")
        m.configure(enabled=False)
        self.assertEqual(m.query()["record_count"],0)
        self.assertFalse(m.enabled)


if __name__ == "__main__":
    unittest.main()
