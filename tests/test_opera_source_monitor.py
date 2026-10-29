"""Test actual public S3 object discovery and provider-driven download orchestration."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import unittest
from test_opera_runtime_atomic import load, runtime_module

monitor_module = load("opera_source_monitor")
NOW = datetime(2026, 10, 29, 18, 30, tzinfo=timezone.utc)

def listing(*keys, truncated="false"):
    items = "".join("<Contents><Key>" + key + "</Key></Contents>" for key in keys)
    return (f"<ListBucketResult><IsTruncated>{truncated}</IsTruncated>{items}</ListBucketResult>").encode()


class S3DiscoveryTests(unittest.TestCase):
    def test_parses_actual_public_s3_key_format_and_time(self):
        data = listing(
            "2026/10/29/OPERA/COMP/OPERA@20261029T1815@0@RATE.tiff",
            "2026/10/29/OPERA/COMP/OPERA@20261029T1810@0@DBZH.tiff")
        found = monitor_module.parse_catalog(data, now=NOW, product="RATE")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1], "OPERA@20261029T1815@0@RATE.tiff")

    def test_catalog_rejects_incomplete_and_wrong_day(self):
        data = listing("2026/10/28/OPERA/COMP/OPERA@20261029T1815@0@RATE.tiff")
        self.assertEqual(monitor_module.parse_catalog(data, now=NOW, product="RATE"), [])
        # The preceding list was complete; explicit truncated response blocks.
        with self.assertRaisesRegex(ValueError, "incomplete_listing"):
            monitor_module.parse_catalog(listing(truncated="true"), now=NOW, product="RATE")

    def test_rejects_old_files_and_untrusted_keys(self):
        keys = ["2026/10/29/OPERA/COMP/OPERA@20261029T1715@0@RATE.tiff",
                "2026/10/29/OPERA/COMP/../../credentials",
                "2026/10/29/OPERA/COMP/OPERA@20261029T1845@0@RATE.tiff"]
        self.assertEqual(monitor_module.parse_catalog(listing(*keys), now=NOW, product="RATE"), [])

    def test_discovery_is_dormant_when_provider_off(self):
        class DummyHass: pass
        runtime = runtime_module.OperaRuntime()
        try:
            monitor = monitor_module.OperaSourceMonitor(
                hass=DummyHass(), session=None, runtime=runtime)
            monitor._list = AsyncMock()
            asyncio.run(monitor.check_once())
            monitor._list.assert_not_called()
            self.assertEqual(monitor.last_reason, "provider_disabled")
        finally:
            runtime.close()

    def test_enabled_rate_tries_once_without_tile_publication(self):
        class DummyHass: pass
        runtime = runtime_module.OperaRuntime()
        runtime.enabled = True
        runtime.services["RATE"] = True
        try:
            monitor = monitor_module.OperaSourceMonitor(
                hass=DummyHass(), session=None, runtime=runtime)
            stamp = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            monitor._list = AsyncMock(return_value=[(stamp, stamp.strftime("OPERA@%Y%m%dT%H%M@0@RATE.tiff"))])
            monitor.fetcher.fetch = AsyncMock(return_value=object())
            asyncio.run(monitor.check_once())
            asyncio.run(monitor.check_once())
            monitor.fetcher.fetch.assert_awaited_once()
            self.assertIsNone(runtime.registry.active("RATE"))
            self.assertEqual(monitor.last_reason, "downloaded_unverified_raster")
        finally:
            runtime.close()

if __name__ == "__main__":
    unittest.main()
