"""Opt-in OPERA RATE watcher; all network I/O async, all disk I/O in HA executor."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from functools import partial
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .opera_odim_metadata import inspect_odim_hdf5
from .providers.opera import BUCKET, MAX_BYTES, validate_key
from .opera_meteogate_discovery import discover_rate_links

INTERVALS = frozenset((15, 20, 30, 60))
MAX_XML = 65536
HDF5_MAGIC = bytes((137, 72, 68, 70, 13, 10, 26, 10))
DOWNLOAD_SAFE_CODES = frozenset(("download_failed", "unexpected_content_encoding", "download_body_incomplete", "invalid_original", "listing_failed", "invalid_listing", "truncated_listing", "odim_metadata_mismatch"))
ODIM_SAFE_CODES = frozenset(("unsupported_product", "unsafe_file", "file_size_invalid", "not_hdf5", "hdf5_dependency_unavailable", "missing_odim_groups", "not_composite", "invalid_odim_utc", "invalid_grid_dimensions", "oversized_grid", "missing_projection", "incomplete_projected_extent", "invalid_projected_extent", "incomplete_geographic_corners", "invalid_geographic_corners", "invalid_data_node", "grid_shape_mismatch", "invalid_calibration", "quantity_missing_or_ambiguous", "hdf5_read_error"))


def expected_slots(now):
    """Current and preceding UTC quarter hour, including midnight rollover."""
    current = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    current = current.replace(minute=(current.minute // 15) * 15)
    # Retain a bounded two-hour lookback for late S3 publications.
    # OPERA can publish frames later than one quarter-hour after nominal UTC.
    return tuple(current - timedelta(minutes=15 * offset) for offset in range(8))


class OperaMonitor:
    def __init__(self, hass, store, *, enabled=False, interval=30):
        if type(interval) is not int or interval not in INTERVALS:
            raise ValueError("invalid_interval")
        self.hass, self.store = hass, store
        self.enabled, self.interval = enabled is True, interval
        self._task = None
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._errors = 0
        self._observations = {}
        self.last_check = None
        self.last_download = None
        self.last_error = None
        self.last_error_code = None
        self.last_error_phase = None
        self.last_attempt_stamp = None
        self.last_successful_store = None
        self.check_count = 0
        self.failed_check_count = 0
        # Listing outcomes are operational evidence, not scientific authorization.
        self.last_listing_outcome = "not_checked"
        self.last_original_origin = None
        self.last_discovery_origin = None
        self.listing_outcome_counts = {key: 0 for key in (
            "listing_ok_0_matching", "listing_ok_multiple", "key_rejected",
            "listing_ok_1_matching", "http_error", "download_failed",
            "odim_rejected", "stored", "admission_denied",
            "primary_empty", "meteo_gate_failed", "meteo_gate_empty")}
        self._root = store.root
        self._metadata_file = self._root / "observations.json"

    def _load(self):
        """Read a strictly bounded owned journal, excluding unsupported fields."""
        if self._metadata_file.is_symlink():
            raise ValueError("unsafe_monitor_metadata")
        if not self._metadata_file.exists():
            return
        if self._metadata_file.stat().st_size > 128 * 1024:
            raise ValueError("oversized_monitor_metadata")
        value = json.loads(self._metadata_file.read_text(encoding="utf-8"))
        if type(value) is not dict or len(value) > 192:
            raise ValueError("invalid_monitor_metadata")
        admitted = {}
        for stamp, record in value.items():
            if not isinstance(stamp, str) or len(stamp) != 16 or type(record) is not dict:
                continue
            try:
                datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
            except ValueError:
                continue
            # Never import arbitrary JSON as later exportable diagnostics.
            allowed = {}
            for key in ("stamp", "first_seen_utc", "download_started_utc",
                        "download_completed_utc", "storage_status", "scientific_status", "origin"):
                val = record.get(key)
                if isinstance(val, str) and len(val) <= 64:
                    allowed[key] = val
            for key in ("observed_delay_seconds", "download_duration_seconds", "bytes"):
                val = record.get(key)
                if type(val) in (int, float) and 0 <= val <= 1e9:
                    allowed[key] = val
            digest = record.get("sha256")
            if isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest):
                allowed["sha256"] = digest
            if allowed.get("origin") not in (None, "cloudferro", "meteo_gate_ecmwf", "meteo_gate_cloudferro"):
                allowed.pop("origin", None)
            if allowed.get("stamp") == stamp and allowed.get("scientific_status") == "UNVERIFIED":
                admitted[stamp] = allowed
        self._observations = admitted
        prior = [v.get("download_completed_utc") for v in admitted.values()
                 if isinstance(v.get("download_completed_utc"), str)]
        self.last_download = max(prior) if prior else None

    def _save(self):
        import os
        from uuid import uuid4
        if self._metadata_file.is_symlink():
            raise ValueError("unsafe_monitor_metadata")
        temp = self._root / (".observations-" + uuid4().hex + ".tmp")
        try:
            with temp.open("x", encoding="utf-8") as handle:
                os.chmod(temp, 0o600)
                json.dump(self._observations, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self._metadata_file)
        finally:
            temp.unlink(missing_ok=True)

    async def start(self):
        if not self.enabled or self._task is not None:
            return
        try:
            await self.hass.async_add_executor_job(self._load)
        except (OSError, ValueError, json.JSONDecodeError):
            self._observations = {}
        self._stop.clear()
        self._task = self.hass.async_create_task(self._run())
        from .diagnostic_center import record
        record(self.hass, category="raster", outcome="started",
               details={"initialized": True})

    async def stop(self):
        self._stop.set()
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        from .diagnostic_center import record
        record(self.hass, category="raster", outcome="unloaded",
               details={"initialized": False})

    async def _run(self):
        while not self._stop.is_set():
            if self.enabled:
                try:
                    await self.check_once()
                    self._errors = 0
                except asyncio.CancelledError:
                    # HA unload must propagate cancellation immediately.
                    raise
                except Exception as exc:
                    # aiohttp and native ODIM failures are not guaranteed to
                    # subclass OSError/ValueError. Never lose the only watcher.
                    self._errors = min(self._errors + 1, 8)
                    self.last_error = type(exc).__name__
                    from .opera_odim_metadata import OdimMetadataError
                    self._listing_outcome(
                        "meteo_gate_failed" if self.last_error_phase == "meteo_gate_discovery"
                        else "odim_rejected" if isinstance(exc, OdimMetadataError) or self.last_error_phase == "odim_validation"
                        else "download_failed" if self.last_error_phase in ("download", "journal")
                        else "http_error" if self.last_error_phase == "s3_listing"
                        else "admission_denied")
                    self.last_error_code = (str(exc) if isinstance(exc, OdimMetadataError)
                                            and str(exc) in ODIM_SAFE_CODES
                                            else str(exc) if type(exc) is ValueError
                                            and str(exc) in DOWNLOAD_SAFE_CODES
                                            else "unclassified_error")
                    self.failed_check_count += 1
                    if self.failed_check_count == 1 or self.failed_check_count % 10 == 0:
                        from .diagnostic_center import record
                        record(self.hass, category="raster", outcome="failed",
                               details={"listing_retry_count": min(self._errors, 8)})
            delay = min(900, self.interval * (2 ** min(self._errors, 4)))
            try:
                await asyncio.wait_for(self._stop.wait(), delay)
            except asyncio.TimeoutError:
                pass

    def _listing_outcome(self, code):
        """Record bounded, secret-free monitor outcomes without claiming data delivery."""
        self.last_listing_outcome = code
        if code in self.listing_outcome_counts:
            self.listing_outcome_counts[code] = min(1000000, self.listing_outcome_counts[code] + 1)

    def _rate_allowed(self):
        """Resolve current server-owned provider/service policy before network I/O."""
        from .const import DOMAIN, CONF_ENABLED_PROVIDERS, CONF_ROUTER_ENABLED
        from .opera_config import service_allowed
        entries = self.hass.config_entries.async_entries(DOMAIN)
        if len(entries) != 1:
            return False
        options = entries[0].options
        return (options.get(CONF_ROUTER_ENABLED, True) is True
                and "opera" in options.get(CONF_ENABLED_PROVIDERS, ())
                and service_allowed(options, "RATE"))

    async def check_once(self):
        if not self.enabled or not self._rate_allowed() or self._lock.locked():
            return {"status": "disabled_or_busy"}
        async with self._lock:
            try:
                now = datetime.now(timezone.utc)
                self.last_check = now.isoformat().replace("+00:00", "Z")
                self.check_count += 1
                session = async_get_clientsession(self.hass)
                stored = {entry["stamp"] for entry in
                          await self.hass.async_add_executor_job(self.store.list_frames)}
                meteo_links = None  # at most one ORD request per monitor check
                for stamp_dt in expected_slots(now):
                    if not self._rate_allowed():
                        return {"status": "provider_or_rate_disabled"}
                    stamp = stamp_dt.strftime("%Y%m%dT%H%M%SZ")
                    self.last_attempt_stamp = stamp
                    self.last_error_phase = "s3_listing"
                    if stamp in stored:
                        continue
                    # Exact object-key prefix, at most eight bounded S3 queries; no pagination.
                    date_prefix = stamp_dt.strftime("%Y/%m/%d")
                    prefix = date_prefix + "/OPERA/COMP/OPERA@" + stamp_dt.strftime("%Y%m%dT%H%M") + "@0@RATE."
                    url = BUCKET + "/?list-type=2&max-keys=4&prefix=" + quote(prefix, safe="")
                    async with asyncio.timeout(10):
                        async with session.get(url, allow_redirects=False, ssl=True) as response:
                            if response.status != 200 or (response.content_length is not None and
                                                         response.content_length > MAX_XML):
                                raise ValueError("listing_failed")
                            raw = await response.content.read(MAX_XML + 1)
                    if len(raw) > MAX_XML or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                        raise ValueError("invalid_listing")
                    try:
                        root = ET.fromstring(raw)
                    except ET.ParseError as exc:
                        raise ValueError("invalid_listing") from exc
                    if root.tag.rsplit("}", 1)[-1] != "ListBucketResult":
                        raise ValueError("invalid_listing")
                    if (root.findtext("{*}IsTruncated") or "").lower() != "false":
                        raise ValueError("truncated_listing")
                    keys = [el.findtext("{*}Key") or "" for el in root.findall("{*}Contents")]
                    selected = []
                    for key in keys:
                        parsed = validate_key(key)
                        if key.startswith(prefix) and parsed and parsed[0] == "RATE" and parsed[1] == stamp_dt and parsed[2] == "h5":
                            selected.append(key)
                    download_origin = "cloudferro"
                    download_url = None
                    if len(selected) > 1:
                        self._listing_outcome("listing_ok_multiple")
                        continue
                    if len(selected) == 1:
                        self._listing_outcome("listing_ok_1_matching")
                        download_url = BUCKET + "/" + quote(selected[0], safe="/@.")
                    else:
                        self._listing_outcome("key_rejected" if keys else "listing_ok_0_matching")
                        if not keys:
                            self._listing_outcome("primary_empty")
                        # The public bucket can be empty while ORD advertises
                        # vetted ECMWF backup objects. Never invent backup keys.
                        if meteo_links is None:
                            self.last_error_phase = "meteo_gate_discovery"
                            meteo_links = await discover_rate_links(session, now)
                        download_url = meteo_links.get(stamp_dt)
                        if download_url is None:
                            self._listing_outcome("meteo_gate_empty")
                            continue
                        download_origin = ("meteo_gate_ecmwf"
                                           if "object-store.os-api.cci1.ecmwf.int" in download_url
                                           else "meteo_gate_cloudferro")
                    self.last_discovery_origin = download_origin
                    self.last_error_phase = "download"
                    observed = datetime.now(timezone.utc)
                    started = datetime.now(timezone.utc)
                    async with asyncio.timeout(15):
                        async with session.get(download_url, allow_redirects=False, ssl=True,
                                               headers={"Accept-Encoding": "identity"},
                                               auto_decompress=False) as response:
                            if response.status != 200 or (response.content_length is not None and response.content_length > MAX_BYTES):
                                raise ValueError("download_failed")
                            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                                raise ValueError("unexpected_content_encoding")
                            advertised_bytes = response.content_length
                            # StreamReader.read(n) may return fewer than n bytes even
                            # while the HTTP body is still being transmitted.
                            chunks = bytearray()
                            async for chunk in response.content.iter_chunked(65536):
                                chunks.extend(chunk)
                                if len(chunks) > MAX_BYTES:
                                    raise ValueError("invalid_original")
                            raw_file = bytes(chunks)
                    finished = datetime.now(timezone.utc)
                    if advertised_bytes is not None and len(raw_file) != advertised_bytes:
                        raise ValueError("download_body_incomplete")
                    if len(raw_file) > MAX_BYTES or not raw_file.startswith(HDF5_MAGIC):
                        raise ValueError("invalid_original")
                    digest = sha256(raw_file).hexdigest()

                    self.last_error_phase = "odim_validation"
                    def validate(path):
                        metadata = inspect_odim_hdf5(path, expected_product="RATE")
                        metadata_stamp = datetime.fromisoformat(metadata.valid_at.replace("Z", "+00:00"))
                        if metadata.product != "RATE" or metadata_stamp != stamp_dt or metadata.raster_approved:
                            raise ValueError("odim_metadata_mismatch")
                        return True

                    result = await self.hass.async_add_executor_job(partial(
                        self.store.store, stamp=stamp, original=raw_file,
                        expected_sha256=digest, validate_original=validate))
                    item = {
                        "stamp": stamp,
                        "first_seen_utc": observed.isoformat().replace("+00:00", "Z"),
                        "download_started_utc": started.isoformat().replace("+00:00", "Z"),
                        "download_completed_utc": finished.isoformat().replace("+00:00", "Z"),
                        "observed_delay_seconds": int((observed - stamp_dt).total_seconds()),
                        "download_duration_seconds": round((finished - started).total_seconds(), 3),
                        "bytes": len(raw_file), "sha256": digest,
                        "storage_status": result["status"], "scientific_status": "UNVERIFIED",
                        "origin": download_origin,
                    }
                    self.last_error_phase = "journal"
                    self._observations[stamp] = item
                    self._observations = dict(sorted(self._observations.items())[-192:])
                    await self.hass.async_add_executor_job(self._save)
                    self.last_download = item["download_completed_utc"]
                    self.last_successful_store = stamp
                    self.last_original_origin = download_origin
                    self._listing_outcome("stored")
                    from .diagnostic_center import record
                    record(self.hass, category="raster", outcome="success",
                           details={"response_bytes": len(raw_file), "frame_count": 1})
                    self.last_error = None
                    self.last_error_code = None
                    self.last_error_phase = None
            finally:
                if not asyncio.current_task().cancelling():
                    await self.hass.async_add_executor_job(self.store.cleanup)
                    # Reconcile the owned ring even when listing/downloading fails
                    # or every slot was already stored. A transient provider error
                    # must not strand an existing valid original.
                    # Registration uses the existing trusted RATE admission;
                    # diagnostics do not grant ordinary provider authorization.
                    from .const import DOMAIN
                    bridge_state = self.hass.data.get(DOMAIN, {}).get("opera_ring_buffer", {})
                    bridge = bridge_state.get("rate_bridge")
                    if bridge is not None and self._rate_allowed():
                        try:
                            previous_stamp = bridge_state.get("last_announced_opera_rate_stamp")
                            previous_status = bridge_state.get("last_announced_opera_rate_status")
                            staged = await self.hass.async_add_executor_job(
                                partial(bridge.stage_latest, allowed=True))
                            bridge_state["last_rate_stage"] = staged
                            # Broadcast only a newly registered frame, never the tiles
                            # or authorization. Every GR subscriber must re-query V2.
                            stamp = staged.get("stamp") if type(staged) is dict else None
                            if (staged.get("status") in ("registered_diagnostic", "registered_approved")
                                    and isinstance(stamp, str)
                                    and (stamp != previous_stamp
                                         or staged.get("status") != previous_status)):
                                bridge_state["last_announced_opera_rate_stamp"] = stamp
                                bridge_state["last_announced_opera_rate_status"] = staged.get("status")
                                self.hass.bus.async_fire("weather_router_opera_cycle_available", {
                                    "provider_id": "opera", "product_id": "RATE",
                                    "stamp": stamp, "scientific_approval": staged.get("status") == "registered_approved",
                                })
                        except Exception:
                            bridge_state["last_rate_stage"] = {
                                "status": "rate_stage_failed", "scientific_status": "UNVERIFIED"}
            return self.snapshot()

    def snapshot(self):
        delays = [v["observed_delay_seconds"] for v in self._observations.values()
                  if type(v.get("observed_delay_seconds")) in (int, float)]
        return {
            "enabled": self.enabled, "interval_seconds": self.interval,
            "last_check_utc": self.last_check, "last_download_utc": self.last_download,
            "last_error_class": self.last_error, "last_error_code": self.last_error_code,
            "last_error_phase": self.last_error_phase, "last_attempt_stamp": self.last_attempt_stamp,
            "check_count": self.check_count,
            "failed_check_count": self.failed_check_count,
            "last_listing_outcome": self.last_listing_outcome,
            "last_original_origin": self.last_original_origin,
            "last_discovery_origin": self.last_discovery_origin,
            "listing_outcome_counts": dict(self.listing_outcome_counts),
            "last_stored_stamp": self.last_successful_store,
            "observations": list(self._observations.values())[-48:],
            "delay_count": len(delays),
            "delay_mean_seconds": round(sum(delays) / len(delays), 1) if delays else None,
            "delay_min_seconds": min(delays) if delays else None,
            "delay_max_seconds": max(delays) if delays else None,
            "scientific_approved": False,
        }
