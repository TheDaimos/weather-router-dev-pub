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
