"""Bounded live OPERA S3 CoG discovery/ingestion; no scientific publication.

Only public known bucket/keys are accepted; filename timestamps are discovery
hints, not measurement proof. A genuine validated raster is required before a
frame may enter Consumer V2 or the authenticated HTTP tile registry.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import quote
from xml.etree import ElementTree as ET

import aiohttp
from .opera_cog_fetch import OperaCogFetch, OPERA_BUCKET, OperaDownloadError

_KEY = re.compile(r"^([0-9]{4})/([0-9]{2})/([0-9]{2})/OPERA/COMP/(OPERA@([0-9]{8})T([0-9]{4})@0@(RATE|DBZH)\.tiff)$")
MAX_LIST_BYTES = 512 * 1024


class OperaCatalogError(ValueError):
    pass


def parse_catalog(payload: bytes, *, now: datetime, product: str):
    """Read strictly bounded public S3 ListObjectsV2 XML, no trust in LastModified."""
    if len(payload) > MAX_LIST_BYTES or product not in ("RATE", "DBZH"):
        raise OperaCatalogError("invalid_listing")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise OperaCatalogError("invalid_listing_xml") from exc
    if root.tag.rsplit("}", 1)[-1] != "ListBucketResult":
        raise OperaCatalogError("unexpected_listing")
    fields = {child.tag.rsplit("}", 1)[-1]: child.text for child in root}
    if fields.get("IsTruncated") != "false":
        raise OperaCatalogError("incomplete_listing")
    selected = []
    for element in root:
        if element.tag.rsplit("}", 1)[-1] != "Contents":
            continue
        key = next((c.text for c in element if c.tag.rsplit("}", 1)[-1] == "Key"), None)
        match = _KEY.fullmatch(key or "")
        if not match or match[7] != product:
            continue
        stamp = datetime.strptime(match[5] + match[6], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        if (stamp.strftime("%Y/%m/%d") != "/".join(match.group(i) for i in (1, 2, 3))
                or not timedelta() <= now - stamp <= timedelta(seconds=900)):
            continue
        selected.append((stamp, match[4]))
    return sorted(set(selected), reverse=True)


class OperaSourceMonitor:
    """One HA-entry-scoped monitor that attempts real network intake on enable."""
    def __init__(self, *, hass, session, runtime, interval=60):
        self.hass, self.session, self.runtime = hass, session, runtime
        self.interval = interval
        self.fetcher = OperaCogFetch(hass=hass, session=session, cache=runtime.cache)
        self._task = None
        self.last_success_utc = None
        self.last_object = None
        self.active_downloads = 0
        self.last_reason = "not_started"
        self._seen = set()

    async def _list(self, product, now):
        prefix = now.strftime("%Y/%m/%d") + "/OPERA/COMP/"
        url = OPERA_BUCKET + "?list-type=2&prefix=" + quote(prefix, safe="")
        timeout = aiohttp.ClientTimeout(total=10)
        async with self.session.get(url, allow_redirects=False, ssl=True,
                                    timeout=timeout) as response:
            if response.status != 200:
                raise OperaCatalogError("source_unavailable")
            length = response.content_length
            if length is not None and length > MAX_LIST_BYTES:
                raise OperaCatalogError("listing_too_large")
            data = await response.content.read(MAX_LIST_BYTES + 1)
        return parse_catalog(data, now=now, product=product)

    async def check_once(self):
        if not self.runtime.enabled:
            self.last_reason = "provider_disabled"
            return
        now = datetime.now(timezone.utc)
        any_found = False
        for product in ("RATE", "DBZH"):
            if self.runtime.services.get(product) is not True:
                continue
            try:
                matches = await self._list(product, now)
                for stamp, name in matches[:1]:
                    key = (product, stamp, name)
                    if key in self._seen:
                        continue
                    self.active_downloads += 1
                    try:
                        frame = await self.fetcher.fetch(filename=name, valid_at=stamp, now=now)
                        self._seen.add(key)
                        self.last_success_utc = datetime.now(timezone.utc)
                        self.last_object = name
                        self.last_reason = "downloaded_unverified_raster"
                        any_found = True
                        # FRAME IS IN PRIVATE CACHE ONLY: scientific metadata,
                        # quality1, palette and provenance must still pass.
                        del frame
                    finally:
                        self.active_downloads -= 1
            except (OperaCatalogError, OperaDownloadError, aiohttp.ClientError,
                    asyncio.TimeoutError, ValueError) as exc:
                self.last_reason = type(exc).__name__
        if not any_found and self.last_reason == "not_started":
            self.last_reason = "no_verified_catalog_objects"

    async def _run(self):
        while self.runtime.enabled:
            try:
                await self.check_once()
            except Exception:
                self.last_reason = "monitor_cycle_failed"
            await asyncio.sleep(self.interval)

    def start(self):
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._run())

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


async def async_apply_opera_provider_selection(hass, *, enabled_providers,
                                                router_enabled, enabled_domains):
    """Use existing router/domain/provider eligibility; no preview switch."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .const import DOMAIN
    area = hass.data.get(DOMAIN, {})
    runtime = area.get("opera_runtime")
    if runtime is None:
        return
    allowed = (router_enabled is True and "weather" in enabled_domains
               and "opera" in enabled_providers and not runtime._closed)
    runtime.enabled = allowed
    runtime.services["RATE"] = allowed
    runtime.services["DBZH"] = False
    runtime.services["ACRR"] = False
    monitor = area.get("opera_source_monitor")
    if not allowed:
        if monitor is not None:
            await monitor.stop()
            area.pop("opera_source_monitor", None)
        return
    if monitor is None:
        monitor = OperaSourceMonitor(
            hass=hass, session=async_get_clientsession(hass), runtime=runtime)
        area["opera_source_monitor"] = monitor
    monitor.start()
