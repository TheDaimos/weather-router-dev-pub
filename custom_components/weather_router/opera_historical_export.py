"""Validate a bounded TEST68-D historical RATE comparison for private Export2Git.

Only metadata and numeric pixel statistics are exportable. Never source bytes,
PNG/base64, paths, arbitrary nested objects, URLs, or scientific approval.
"""
from __future__ import annotations
from datetime import datetime
import re

_SCHEMA = "weather_router.opera.test68_d.historical.v1"
_SHA = re.compile(r"[0-9a-f]{64}")
_STAMP = re.compile(r"[0-9]{8}T[0-9]{6}Z")
_STATS = (
    "total_pixels", "valid_pixels", "nodata_pixels", "undetect_pixels",
    "transparent_pixels", "precipitation_pixels", "minimum_precipitation",
    "maximum_precipitation", "png_bytes",
)
_ALLOWED = {
    "schema", "test_id", "mode", "selected_observation_utc",
    "selected_frame_sha256", "selected_frame_identifier", "z", "x", "y",
    "north_first", "south_first", "scientific_approval",
    "consumer_v2_authorized", "weather_warnings_authorized",
    "configured_preview_validity_seconds", "effective_preview_validity_seconds",
    "stale_after_seconds", "serve_stale", "historical_live_age_bypass",
}

class HistoricalExportRejected(ValueError):
    pass

def _integer(value, low=0, high=100000000):
    return type(value) is int and low <= value <= high

def validate_historical_export(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict) or set(snapshot) - _ALLOWED:
        raise HistoricalExportRejected("invalid_historical_snapshot_keys")
    if (snapshot.get("schema") != _SCHEMA or snapshot.get("test_id") != "TEST68-D"
            or snapshot.get("mode") != "historical_diagnostic"
            or snapshot.get("scientific_approval") is not False
            or snapshot.get("consumer_v2_authorized") is not False
            or snapshot.get("weather_warnings_authorized") is not False):
        raise HistoricalExportRejected("historical_snapshot_guard_invalid")
    stamp = snapshot.get("selected_frame_identifier")
    sha = snapshot.get("selected_frame_sha256")
    iso = snapshot.get("selected_observation_utc")
    if (not isinstance(stamp,str) or not _STAMP.fullmatch(stamp)
            or not isinstance(sha,str) or not _SHA.fullmatch(sha)
            or not isinstance(iso,str) or len(iso)>40):
        raise HistoricalExportRejected("invalid_historical_frame_identity")
    try:
        if datetime.fromisoformat(iso.replace("Z","+00:00")).strftime("%Y%m%dT%H%M%SZ") != stamp:
            raise ValueError("timestamp mismatch")
    except ValueError as exc:
        raise HistoricalExportRejected("invalid_historical_utc") from exc
    z,x,y = (snapshot.get(k) for k in ("z","x","y"))
    if not _integer(z,0,12) or not _integer(x,0,(1<<z)-1) or not _integer(y,0,(1<<z)-1):
        raise HistoricalExportRejected("invalid_historical_tile")
    for name in ("north_first","south_first"):
        data=snapshot.get(name)
        if not isinstance(data,dict) or set(data)!={"status","png_bytes","pixel_statistics"}:
            raise HistoricalExportRejected("invalid_historical_orientation")
        if data["status"]!="rendered_unverified" or not _integer(data["png_bytes"],1,512*1024):
            raise HistoricalExportRejected("invalid_historical_png_metadata")
        stats=data["pixel_statistics"]
        if not isinstance(stats,dict) or set(stats)-set(_STATS):
            raise HistoricalExportRejected("invalid_historical_statistics")
        for key,value in stats.items():
            if key in ("minimum_precipitation","maximum_precipitation"):
                if value is not None and (type(value) not in (int,float) or not 0<=value<=10000000):
                    raise HistoricalExportRejected("invalid_historical_statistics")
            elif not _integer(value):
                raise HistoricalExportRejected("invalid_historical_statistics")
    for key in ("configured_preview_validity_seconds","effective_preview_validity_seconds","stale_after_seconds"):
        if key in snapshot and not _integer(snapshot[key],0,86400):
            raise HistoricalExportRejected("invalid_historical_policy")
    for key in ("serve_stale","historical_live_age_bypass"):
        if key in snapshot and type(snapshot[key]) is not bool:
            raise HistoricalExportRejected("invalid_historical_policy")
    # Return a new bounded payload, not the browser-provided reference.
    return {key:snapshot[key] for key in _ALLOWED if key in snapshot}
