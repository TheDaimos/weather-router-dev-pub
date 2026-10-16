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
