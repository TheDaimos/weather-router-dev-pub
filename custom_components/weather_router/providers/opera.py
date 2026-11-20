"""EUMETNET OPERA discovery-only provider, with no raster or V2 activation.

All I/O is explicitly requested by the existing admin-only provider diagnostic.
An enabled provider is still NOT authorization for scientific tile delivery.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

_SAFE_S3_ERRORS = frozenset(("AccessDenied", "NoSuchBucket", "InvalidArgument", "InvalidToken", "RequestTimeout", "SlowDown", "InternalError", "ServiceUnavailable"))

def _safe_s3_code(root):
    code = (root.findtext("{*}Code") or "").strip()
    return code if code in _SAFE_S3_ERRORS else "unknown_s3_error"


from homeassistant.helpers.aiohttp_client import async_get_clientsession
from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

BUCKET = "https://s3.waw3-1.cloudferro.com/openradar-24h"
MAX_BYTES = 12 * 1024 * 1024
MAX_LISTED_BYTES = 512 * 1024 * 1024  # metadata only; never auto-download large originals
MAX_KEYS = 1000
MAX_RETURNED_OBJECTS = 100
TIMEOUT = 10
MAX_LISTING_PAGES = 128  # hard page budget; never unbounded
RECENT_WINDOW_HOURS = 3  # scoped recent-object discovery, not a full-day inventory
KEY = re.compile(r"^(20\d{2})/(\d{2})/(\d{2})/OPERA/COMP/OPERA@(20\d{6})T(\d{4})@0@(RATE|DBZH|ACRR)\.(tiff|h5)$")
PRODUCTS = ("RATE", "DBZH", "ACRR")
CAPS = (
    CapabilityInfo("opera_rate_discovery", "OPERA NIMBUS · RATE (nur Diagnose)", "mm/h", "observation",
                   "value", "Originalobjekt- und Verbindungsdiagnose; Raster gesperrt"),
    CapabilityInfo("opera_rate_history", "OPERA RATE · historische ODIM-Prüfung (DEV)", "mm/h", "observation",
                   "value", "Administrativer Einzelabruf, keine Kacheln, automatische Bereinigung"),
    CapabilityInfo("opera_dbzh_discovery", "OPERA CIRRUS · DBZH (nur Diagnose)", "dBZ", "observation",
                   "value", "Originalobjekt- und Verbindungsdiagnose; Raster gesperrt"),
)

def validate_key(key):
    match = KEY.fullmatch(key or "")
    if match is None or "".join(match.group(i) for i in (1,2,3)) != match.group(4):
        return None
    try:
        date = datetime.strptime(match.group(4) + match.group(5), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (match.group(6), date, match.group(7))

def parse_listing(raw, *, expected_day, allow_truncated=False):
    if len(raw) > 512 * 1024:
        raise ValueError("oversized_listing")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("forbidden_xml_markup")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("invalid_listing_xml") from exc
    if root.tag.rsplit("}", 1)[-1] != "ListBucketResult":
        raise ValueError("unexpected_listing_root")
    # A single truncated S3 page must never masquerade as complete availability.
    if not allow_truncated and (root.findtext("{*}IsTruncated") or "").strip().lower() == "true":
        raise ValueError("incomplete_object_listing")
    objects = []
    for item in root.findall("{*}Contents")[:MAX_KEYS]:
        key = item.findtext("{*}Key") or ""
        parsed = validate_key(key)
        if parsed and key.startswith(expected_day + "/") and parsed[0] in PRODUCTS:
            size = item.findtext("{*}Size") or ""
            if size.isdecimal() and 0 < int(size) <= MAX_LISTED_BYTES:
                objects.append({"product": parsed[0], "key": key,
                                "nominal_filename_utc": parsed[1].isoformat().replace("+00:00", "Z"),
                                "bytes": int(size), "format": "ODIM_HDF5" if parsed[2] == "h5" else "TIFF_UNVERIFIED",
                                "valid_at_scientific": "unverified"})
    return sorted(objects, key=lambda item: item["nominal_filename_utc"], reverse=True)[:MAX_KEYS]

class OperaProvider:
    id = "opera"
    name = "EUMETNET OPERA"
    router_display_group = "precipitation"
    revision = "f7-opera-s3-xml-recovery-5"

    def capabilities(self):
        return CAPS

    def provider_info(self):
        return ProviderInfo(
            summary="OPERA Originaldaten: ausdrücklich auslösbare native-freie Diagnose; Rasterdarstellung gesperrt.",
            coverage="Europa; tatsächliche Originalpixel-Abdeckung noch nicht verifiziert",
            strengths=("Amtliche EUMETNET-Originaldaten", "Öffentlicher Object-Store"),
            limitations=("Keine fachliche V2-Rasterfreigabe", "UTC im Dateinamen nur nominell",
                         "Kein automatischer Hintergrundabruf"),
            documentation_url="https://eumetnet.github.io/openradardata-documentation/",
            attribution="EUMETNET OPERA",
            services=({"name":"RATE / NIMBUS", "status":"Diagnose"},
                      {"name":"DBZH / CIRRUS", "status":"Diagnose"}),
        )

    def network_targets(self):
        return (NetworkTargetInfo(
            purpose="public_opera_original_object_discovery", scheme="https",
            host="s3.waw3-1.cloudferro.com", port=443, target_type="object_storage",
            required=False, capabilities=tuple(cap.id for cap in CAPS),
            note="Nur ausdrücklicher Diagnosetest; keine automatischen Abrufe."),)

    async def async_diagnostics(self, hass, capability_id=None):
        """Trace actual opt-in S3 diagnostic phases without exporting raw frames."""
        from time import monotonic
        from ..diagnostic_center import record as d2_record
        started = monotonic()
        d2_record(hass, category="raster", outcome="started", details={})
        try:
            result = await self._async_diagnostics_impl(hass, capability_id)
        except Exception:
            d2_record(hass, category="raster", outcome="failed",
                      details={"duration_ms": round((monotonic() - started) * 1000, 2)})
            raise
        d2_record(hass, category="raster",
                  outcome="success" if result.get("ok") is True else "failed",
                  details={
                      "duration_ms": round((monotonic() - started) * 1000, 2),
                      "http_status": result.get("listing_http_status"),
                      "listing_pages": result.get("listing_pages"),
                      "listing_response_bytes": result.get("listing_response_bytes"),
                      "listing_retry_count": result.get("listing_retry_count"),
                      "listing_objects_seen": result.get("listing_objects_seen"),
                      "listing_complete": result.get("listing_complete"),
                  })
        return result

    async def _async_diagnostics_impl(self, hass, capability_id=None):
        """The existing diagnostic endpoint enforces user/router/provider permissions.

        Default test reads a single current-day, capped listing. Selecting RATE
        explicitly also downloads ONE listed original into bounded memory.
        No TIFF pixels are interpreted or passed to the consumer API.
        """
        if capability_id not in (None, "opera_rate_discovery", "opera_rate_history", "opera_dbzh_discovery"):
            return {"ok":False, "stage":"invalid_capability"}
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y/%m/%d")
        report = {"schema":"weather_router.opera.provider_diagnostic.v1",
                  "stage":"original_discovery", "raster_status":"BLOCKED",
                  "consumer_v2_status":"BLOCKED", "no_native_imports":True,
                  "scientific_valid_at":"NOT_VERIFIED", "products":[], "objects":[]}
        # S3 ListObjectsV2 is lexicographically ordered, not newest-first.
        # The OPERA filenames begin with OPERA@YYYYMMDDTHHMM; StartAfter
        # skips older keys server-side without guessing from page counts.
        # A window crossing UTC midnight stays within today's day prefix;
        # the preceding day is deliberately NOT claimed as covered.
        window_start = max(now - timedelta(hours=RECENT_WINDOW_HOURS),
                           now.replace(hour=0, minute=0, second=0, microsecond=0))
        start_after = day + "/OPERA/COMP/OPERA@" + window_start.strftime("%Y%m%dT%H%M")
        base_url = (BUCKET + "/?list-type=2&max-keys=1000&prefix="
                    + quote(day + "/OPERA/COMP/", safe="")
                    + "&start-after=" + quote(start_after, safe=""))
        report["listing_scope"] = "recent_window_only"
        report["listing_window_start_utc"] = window_start.isoformat().replace("+00:00", "Z")
        report["full_day_inventory_complete"] = False
        try:
            session = async_get_clientsession(hass)
            objects = []
            report["listing_pages"] = 0
            report["listing_truncated"] = None
            report["listing_objects_seen"] = 0
            report["listing_complete"] = False
            token = None
            seen_tokens = set()
            # Bounded pagination is required: S3 can return IsTruncated=true.
            # Never claim a complete inventory if the bounded page budget is exceeded.
            async with asyncio.timeout(TIMEOUT * 12):
                for page in range(MAX_LISTING_PAGES):
                    # 4096-byte incomplete XML seen on VM109. No 4-KiB
                    # application cap exists. Retry once with fewer S3 keys;
                    # never accept an incomplete page as complete.
                    root = None
                    for attempt, max_keys in enumerate((1000, 5)):
                        url = (base_url.replace("max-keys=1000", "max-keys=" + str(max_keys))
                               + ("&continuation-token=" + quote(token, safe="") if token else ""))
                        async with session.get(url, allow_redirects=False, ssl=True,
                                               headers={"Accept-Encoding":"identity"}) as response:
                            report["listing_http_status"] = response.status
                            report["listing_content_type"] = response.headers.get("Content-Type", "").split(";")[0].strip().lower()[:80]
                            report["listing_content_length"] = response.content_length
                            report["listing_pages"] = page + 1
                            if response.status != 200:
                                return {**report, "ok":False, "error":"listing_http_status"}
                            if response.content_length is not None and response.content_length > 512*1024:
                                return {**report, "ok":False, "error":"listing_size_limit"}
                            raw = await response.content.read(512*1024 + 1)
                        report["listing_response_bytes"] = len(raw)
                        # Measured S3 bytes only: never retain URL, token or XML.
                        from ..diagnostic_center import record as d2_record
                        d2_record(hass, category="raster", outcome="success" if response.status == 200 else "failed",
                                  details={"http_status": response.status,
                                           "listing_response_bytes": len(raw),
                                           "listing_pages": page + 1,
                                           "listing_retry_count": attempt})
                        report["listing_retry_count"] = attempt
                        if len(raw) > 512*1024:
                            return {**report, "ok":False, "error":"listing_size_limit"}
                        if report["listing_content_length"] is not None and len(raw) != report["listing_content_length"]:
                            report["listing_length_mismatch"] = True
                            if attempt == 0:
                                continue
                            return {**report, "ok":False, "error":"listing_body_incomplete"}
                        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                            return {**report, "ok":False, "error":"forbidden_xml_markup"}
                        try:
                            root = ET.fromstring(raw)
                            break
                        except ET.ParseError as exc:
                            report["parse_error_class"] = type(exc).__name__
                            report["parse_error_line"] = exc.position[0]
                            report["parse_error_column"] = exc.position[1]
                            if attempt == 0:
                                continue
                            return {**report, "ok":False, "error":"invalid_listing_xml"}
                    if root is None:
                        return {**report, "ok":False, "error":"invalid_listing_xml"}
                    root_name = root.tag.rsplit("}", 1)[-1]
                    report["listing_root"] = root_name[:80] if root_name in ("ListBucketResult", "Error") else "unexpected_root"
                    if root_name != "ListBucketResult":
                        return {**report, "ok":False,
                                "error":"s3_error_response" if root_name == "Error" else "unexpected_listing_root",
                                "s3_error_code":_safe_s3_code(root) if root_name == "Error" else None}
                    # Reject endpoints that ignore the requested lower bound.
                    # Key ordering is a requirement for scoped discovery.
                    returned_start = root.findtext("{*}StartAfter")
                    page_keys = [item.findtext("{*}Key") or "" for item in root.findall("{*}Contents")]
                    if page == 0 and returned_start != start_after:
                        return {**report, "ok":False, "error":"start_after_not_confirmed"}
                    if any(key <= start_after or not key.startswith(day + "/OPERA/COMP/")
                           for key in page_keys):
                        return {**report, "ok":False, "error":"listing_outside_requested_window"}
                    if page_keys != sorted(page_keys):
                        return {**report, "ok":False, "error":"listing_order_invalid"}
                    next_token = root.findtext("{*}NextContinuationToken")
                    truncated_text = (root.findtext("{*}IsTruncated") or "").strip().lower()
                    if truncated_text not in ("true", "false"):
                        return {**report, "ok":False, "error":"invalid_truncation_flag"}
                    truncated = truncated_text == "true"
                    report["listing_truncated"] = truncated
                    # Reuse existing strict parser, but only when a page is complete.
                    try:
                        parsed_page = parse_listing(raw, expected_day=day, allow_truncated=True)
                        report["listing_objects_seen"] += len(root.findall("{*}Contents"))
                        objects.extend(parsed_page)
                    except ValueError as exc:
                        return {**report, "ok":False, "error":str(exc)}
                    report["listing_pages"] = page + 1
                    if not truncated:
                        break
                    if (not next_token or not 1 <= len(next_token) <= 512
                            or next_token in seen_tokens or page == MAX_LISTING_PAGES - 1):
                        return {**report, "ok":False, "error":"incomplete_object_listing"}
                    seen_tokens.add(next_token)
                    token = next_token
            objects = list({obj["key"]: obj for obj in objects}.values())
            if capability_id in ("opera_rate_discovery", "opera_rate_history"):
                objects = [obj for obj in objects if obj["product"] == "RATE"]
            elif capability_id == "opera_dbzh_discovery":
                objects = [obj for obj in objects if obj["product"] == "DBZH"]
            objects = sorted(objects, key=lambda item:item["nominal_filename_utc"], reverse=True)
            report["rate_matches"] = sum(item["product"] == "RATE" for item in objects)
            # Expose the actual newest validated RATE candidate even when the
            # generic provider diagnostic displays only the first ten objects.
            # This metadata is NOT a verified HDF5 or scientific raster.
            rate_candidates = [item for item in objects if item["product"] == "RATE"
                               and item["format"] == "ODIM_HDF5"]
            # A lexically valid filename is not necessarily a current frame.
            # Decline future/old frames rather than staging arbitrary pixels.
            # The server-owned OPERA settings define the preview eligibility window.
            # Use a fresh timestamp after listing, not the listing start time.
            from ..opera_preview_age_policy import preview_continuity_from_entries
            from ..const import DOMAIN
            entries = hass.config_entries.async_entries(DOMAIN)
            options = entries[0].options if entries else {}
            max_rate_age_seconds = preview_continuity_from_entries(entries)["delivery_limit_seconds"]
            selection_now = datetime.now(timezone.utc)
            eligible_rate = [item for item in rate_candidates
                             if 0 <= (selection_now - datetime.fromisoformat(
                                 item["nominal_filename_utc"].replace("Z", "+00:00")
                             )).total_seconds() <= max_rate_age_seconds]
            report["rate_hdf5_eligible"] = len(eligible_rate)
            report["rate_max_age_seconds"] = max_rate_age_seconds
            # Explicit trace of the *live* staging gate, independent of the
            # historical HDF5 metadata probe. Do not disclose raw object keys.
            report["diagnostic_registration"] = {
                "requested": capability_id == "opera_rate_discovery",
                "fresh_original_available": bool(eligible_rate),
                "fresh_candidate_count": len(eligible_rate),
                "rate_candidate_count": len(rate_candidates),
                "status": ("eligible_for_staging" if eligible_rate
                           else "no_fresh_rate_original"),
                "scientific_approval": False,
            }
            report["rate_selection_checked_at_utc"] = selection_now.isoformat().replace("+00:00", "Z")
            report["rate_hdf5_matches"] = len(rate_candidates)
            report["latest_rate_hdf5"] = dict(eligible_rate[0]) if eligible_rate else None
            report["rate_hdf5_selected_for_download"] = (
                capability_id == "opera_rate_discovery" and bool(eligible_rate)
            )
            report["dbzh_matches"] = sum(item["product"] == "DBZH" for item in objects)
            report["acrr_matches"] = sum(item["product"] == "ACRR" for item in objects)
            report["listing_complete"] = True  # scoped time window only, not full day
            report["products"] = sorted({obj["product"] for obj in objects})
            report["objects"] = objects[:10]
            report["object_count"] = len(objects)
            objects = objects[:MAX_RETURNED_OBJECTS]
            report["ok"] = True
            report["status"] = "originals_listed_raster_blocked" if objects else "connection_ready_no_current_object"
            if capability_id not in ("opera_rate_discovery", "opera_rate_history") or not objects:
                return report
            # HDF5 RATE is now staged solely by explicit admin diagnostics.
            # No periodic download, provider auto-selection or scientific release.
            historical = capability_id == "opera_rate_history"
            chosen_hdf5 = (rate_candidates[0] if historical and rate_candidates else
                           eligible_rate[0] if eligible_rate else None)
            if chosen_hdf5 is None:
                return {**report, "download": "BLOCKED", "error": ("no_historical_rate_object" if historical else "no_fresh_rate_object"),
                        "stage": "rate_freshness_selection",
                        "diagnostic_registration": {
                            **report["diagnostic_registration"],
                            "status": "not_registered_no_fresh_original",
                            "frame_registered": False,
                        }}
            if chosen_hdf5 is not None:
                # Native module probing can import compiled libraries: run only
                # inside the HA executor, before allocating or fetching HDF5 bytes.
                from ..opera_runtime_dependencies import inspect_rate_runtime
                runtime = await hass.async_add_executor_job(inspect_rate_runtime)
                if runtime.get("runtime_importable") is not True:
                    return {**report, "download": "BLOCKED",
                            "error": "hdf5_dependency_unavailable",
                            "stage_failure_code": "native_rate_runtime_unavailable",
                            "runtime_blockers": list(runtime.get("blockers", []))[:8]}
                selected = chosen_hdf5
                if selected["bytes"] > MAX_BYTES:
                    return {**report, "download":"BLOCKED", "error":"hdf5_size_limit"}
                url = BUCKET + "/" + selected["key"]
                data = bytearray()
                async with asyncio.timeout(TIMEOUT):
                    async with session.get(url,allow_redirects=False,ssl=True,
                                           headers={"Accept-Encoding":"identity"}) as response:
                        if response.status != 200 or (response.content_length is not None and
                                response.content_length != selected["bytes"]):
                            return {**report,"download":"BLOCKED","error":"hdf5_response_invalid"}
                        async for chunk in response.content.iter_chunked(65536):
                            data.extend(chunk)
                            if len(data) > MAX_BYTES or len(data) > selected["bytes"]:
                                return {**report,"download":"BLOCKED","error":"hdf5_size_limit"}
                if len(data) != selected["bytes"] or data[:8] != bytes((137,72,68,70,13,10,26,10)):
                    return {**report,"download":"BLOCKED","error":"hdf5_invalid"}
                # Explicit, authorized provider diagnostic is the sole writer.
                # Source keys are obtained from the strict S3 listing parser, not a user.
                from ..const import DOMAIN
                ring_state = hass.data.get(DOMAIN, {}).get("opera_ring_buffer", {})
                ring_store = ring_state.get("store") if isinstance(ring_state, dict) else None
                if ring_store is not None and ring_state.get("monitor_enabled") is True:
                    from functools import partial
                    from ..opera_odim_metadata import inspect_odim_hdf5
                    nominal = datetime.fromisoformat(
                        selected["nominal_filename_utc"].replace("Z", "+00:00"))
                    expected_stamp = nominal.strftime("%Y%m%dT%H%M%SZ")
                    digest_for_ring = sha256(data).hexdigest()

                    def _admit_original(owned_path):
                        metadata = inspect_odim_hdf5(owned_path, expected_product="RATE")
                        verified_time = datetime.fromisoformat(
                            metadata.valid_at.replace("Z", "+00:00"))
                        if (verified_time != nominal or metadata.product != "RATE"
                                or metadata.raster_approved is True):
                            raise ValueError("odim_time_or_product_mismatch")
                        return True

                    try:
                        ring_result = await hass.async_add_executor_job(partial(
                            ring_store.store, stamp=expected_stamp, original=bytes(data),
                            expected_sha256=digest_for_ring,
                            validate_original=_admit_original))
                        stored_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                        ring_state["manual_last_download_utc"] = stored_at
                        ring_state["manual_last_stamp_utc"] = selected["nominal_filename_utc"]
                        ring_state["manual_last_store_status"] = ring_result["status"]
                        report["ring_buffer"] = {
                            "status": ring_result["status"],
                            "origin": "manual_provider_diagnostic",
                            "storage": await hass.async_add_executor_job(ring_store.snapshot),
                            "scientific_approval": False,
                        }
                    except (OSError, ValueError):
                        report["ring_buffer"] = {"status": "admission_failed",
                                                 "scientific_approval": False}
                if historical:
                    from ..opera_historical_diagnostic import cleanup_orphans, inspect_historical_bytes
                    try:
                        cleanup_count = await hass.async_add_executor_job(cleanup_orphans)
                        from functools import partial
                        history = await hass.async_add_executor_job(partial(
                            inspect_historical_bytes, bytes(data),
                            expected_filename_utc=selected["nominal_filename_utc"]))
                        return {**report, "download": history, "historical": True,
                                "cleanup_orphans_removed": cleanup_count,
                                "consumer_v2_status": "BLOCKED", "raster_status": "BLOCKED"}
                    except Exception as exc:
                        code = str(exc) if isinstance(exc, ValueError) else ""
                        allowed = {"invalid_historical_hdf5", "unsafe_history_directory",
                                   "missing_odim_groups", "invalid_odim_utc", "invalid_grid_dimensions",
                                   "oversized_grid", "missing_projection", "quantity_missing_or_ambiguous",
                                   "hdf5_dependency_unavailable", "hdf5_read_error"}
                        return {**report, "download": "BLOCKED", "historical": True,
                                "error": "historical_odim_inspection_failed",
                                "stage_failure_code": code if code in allowed else "unclassified_history_failure",
                                "cleanup": "attempted"}
                from ..const import DOMAIN
                stage = hass.data.get(DOMAIN, {}).get("opera_rate_delivery", {})
                # Administrator opt-in is persisted in Config Entry options,
                # not in the process-local opera_preview dictionary.
                preview_enabled = any(
                    entry.options.get("opera_dev_preview_enabled") is True
                    for entry in hass.config_entries.async_entries(DOMAIN)
                )
                if not (stage.get("enabled") is True or preview_enabled) or not stage.get("delivery"):
                    return {**report,"download":"BLOCKED","error":"diagnostic_runtime_disabled"}
                import tempfile
                from pathlib import Path
                import os
                fd, name = tempfile.mkstemp(prefix="wr-opera-rate-",suffix=".h5")
                try:
                    with os.fdopen(fd,"wb") as out:
                        out.write(data)
                    os.chmod(name,0o600)
                    digest=sha256(data).hexdigest()
                    del data
                    def stage_worker():
                        from ..opera_odim_metadata import inspect_odim_hdf5
                        from ..opera_odim_reconstruction import reconstruct_laea
                        local=Path(name)
                        inspection=inspect_odim_hdf5(local,expected_product="RATE")
                        # Source-owned ODIM metadata, never hard-coded coordinates.
                        # North-first is a DEV rendering hypothesis ONLY.
                        if inspection.geographic_corners is None or inspection.pixel_scale is None:
                            raise ValueError("odim_source_georeference_missing")
                        grid=reconstruct_laea(
                            projection=inspection.projection,
                            corners=inspection.geographic_corners,
                            width=inspection.width,height=inspection.height,
                            xscale=inspection.pixel_scale[0],
                            yscale=inspection.pixel_scale[1],
                            row_zero_north=True)
                        return stage["delivery"].stage_local_rate(
                            trusted_path=local,expected_sha256=digest,
                            diagnostic_grid=grid,attribution="EUMETNET OPERA · Unverified DEV")
                    stamp=await hass.async_add_executor_job(stage_worker)
                except Exception as exc:
                    # Only fixed allowlisted error codes leave the trusted executor.
                    # Never export local paths, exception messages or original bytes.
                    known = {"native_rate_runtime_unavailable", "hdf5_dependency_unavailable",
                             "missing_odim_groups", "invalid_odim_utc", "invalid_grid_dimensions",
                             "oversized_grid", "unverified_projection", "unexpected_rate_grid",
                             "odim_source_georeference_missing",
                             "unverified_diagnostic_grid", "stale_or_future_source",
                             "source_digest_mismatch", "untrusted_source",
                             "diagnostic_runtime_disabled"}
                    reason = str(exc) if isinstance(exc, ValueError) else ""
                    return {**report, "download":"BLOCKED",
                            "error":"hdf5_diagnostic_stage_failed",
                            "stage_failure_code": reason if reason in known else "unclassified_stage_failure"}
                finally:
                    Path(name).unlink(missing_ok=True)
                # Authenticated staging only; report digest and frame time via
                # existing diagnostics, never persist original bytes.
                from ..diagnostic_center import record as d2_record
                d2_record(hass, category="raster", outcome="success",
                          details={"response_bytes": selected["bytes"], "frame_count": 1})
                report["download"]={"status":"dev_diagnostic_unverified",
                                    "bytes":selected["bytes"],"sha256":digest,
                                    "frame_utc":stamp,"scientific_approval":False}
                report["hdf5_sha256_verified"]=True
                report["odim_structure_verified"]=True
                report["diagnostic_frame_registered"]=True
                report["diagnostic_registration"] = {
                    **report["diagnostic_registration"],
                    "status": "registered_unverified",
                    "frame_registered": True,
                }
                report["original_pixels_scientifically_verified"]=False
                report["raster_status"]="DIAGNOSTIC_ONLY_UNVERIFIED"
                report["consumer_v2_status"]="ADMIN_DIAGNOSTIC_ONLY"
                return report
            if objects[0]["format"] != "TIFF_UNVERIFIED":
                return {**report,"download":"BLOCKED","error":"unsupported_format"}
            # Explicit RATE diagnostic only. The object path is from a strict
            # checked public list; all redirects, size overruns and failures deny.
            chosen = objects[0]
            url = BUCKET + "/" + chosen["key"]
            data = bytearray()
            async with asyncio.timeout(TIMEOUT):
                async with session.get(url, allow_redirects=False, ssl=True,
                                       headers={"Accept-Encoding":"identity"}) as response:
                    if response.status != 200 or (response.content_length is not None and
                                                   response.content_length != chosen["bytes"]):
                        return {**report, "download":"BLOCKED", "error":"object_response_invalid"}
                    async for chunk in response.content.iter_chunked(65536):
                        data.extend(chunk)
                        if len(data) > MAX_BYTES or len(data) > chosen["bytes"]:
                            return {**report, "download":"BLOCKED", "error":"download_size_limit"}
            if len(data) != chosen["bytes"] or data[:4] not in (b"II*\x00", b"MM\x00*",
                                                                  b"II+\x00", b"MM\x00+"):
                return {**report, "download":"BLOCKED", "error":"object_truncated_or_not_tiff"}
            report["download"] = {"status":"original_bytes_verified_only",
                                  "bytes":len(data), "sha256":sha256(data).hexdigest()}
            return report
        except (asyncio.TimeoutError, ValueError, ET.ParseError) as exc:
            return {**report, "ok":False, "error":type(exc).__name__}
        except Exception:
            return {**report, "ok":False, "error":"network_or_decode_error"}
