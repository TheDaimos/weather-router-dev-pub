"""Official NOAA/WPC coded surface front vectors (North America only).

No forecast contour inference: each LineString comes from a typed frontal
coordinate sequence in an officially published coded surface bulletin.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import re
from time import monotonic
from urllib.parse import urljoin

from .synoptic_wpc import (
    ROOT, MAX_INDEX_BYTES, MAX_BULLETIN_BYTES,
    Listing, WpcUnavailable, _fetch, _datetime,
)
from .spatial_coverage import bbox_overlaps, normalize_bbox

CAPABILITY = "weather.synoptic.fronts"
# Conservative delivery envelope for the coded product, including the
# southern fringe of the North American chart. It is not a land mask.
COVERAGE = {"type": "bbox", "crs": "EPSG:4326",
            "west": -180., "east": -30., "south": 20., "north": 80.}
TYPES = {"COLD": "cold", "WARM": "warm",
         "OCFNT": "occluded", "STNRY": "stationary"}
BOUNDARIES = frozenset(("HIGHS", "LOWS", "COLD", "WARM",
    "OCFNT", "STNRY", "TROF", "TROUGH", "OUTFLOW",
    "DISS", "RIDGE", "ISOBAR", "VALID", "FRONT"))
INTENSITIES = frozenset(("WK", "MDT", "STG"))
MAX_FRONTS = 160
MAX_POINTS = 240


def _point(token: str) -> list[float] | None:
    """Official low/high resolution coordinates: latitude N, longitude W."""
    if not token.isdecimal():
        return None
    if len(token) in (4, 5):
        lat, lon = int(token[:2]), int(token[2:])
    elif len(token) == 7:
        lat, lon = int(token[:3]) / 10, int(token[3:]) / 10
    else:
        return None
    if not (0 <= lat <= 85 and 0 <= lon <= 180):
        return None
    return [-lon, lat]


def decode_fronts(payload: bytes, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if not payload or len(payload) > MAX_BULLETIN_BYTES:
        raise WpcUnavailable("synoptic_fronts_transport_budget")
    try:
        content = payload.decode("ascii", errors="strict").upper()
    except UnicodeError as error:
        raise WpcUnavailable("synoptic_fronts_invalid_encoding") from error
    stamp = re.search(r"\bVALID\s+(\d{6})Z\b", content)
    if stamp is None:
        raise WpcUnavailable("synoptic_fronts_missing_validity")
    valid = _datetime(stamp.group(1), now)
    # Stop only at the start of another official coded feature; wrapped lines
    # and repeated front classes remain distinct separate LineStrings.
    tokens = content[stamp.end():].split("$$", 1)[0].split()
    features = []
    current = None
    points = []
    intensity = None

    def flush():
        if current is None:
            return
        if len(points) < 2:
            raise WpcUnavailable("synoptic_fronts_incomplete_path")
        if len(features) >= MAX_FRONTS:
            raise WpcUnavailable("synoptic_fronts_feature_budget")
        # No inferred movement or front-facing side from line order.
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [p[:] for p in points]},
            "properties": {"front_type": current,
                           "intensity": intensity,
                           "symbol_side": None,
                           "symbol_side_authorized": False},
        })

    for token in tokens:
        if token in BOUNDARIES:
            flush()
            current = TYPES.get(token)
            points = []
            intensity = None
            continue
        if current is None:
            continue
        if token in INTENSITIES and not points and intensity is None:
            intensity = token.lower()
            continue
        p = _point(token)
        if p is None:
            # Never silently convert malformed mixed text into geometry.
            raise WpcUnavailable("synoptic_fronts_invalid_coordinates")
        if len(points) >= MAX_POINTS:
            raise WpcUnavailable("synoptic_fronts_point_budget")
        points.append(p)
    flush()
    if not features and not re.search(r"\bHIGHS\s+\d{3,4}\s+\d{4,7}\b", content[stamp.end():]):
        raise WpcUnavailable("synoptic_fronts_no_verified_paths")
    until = min(now + timedelta(minutes=25), valid + timedelta(hours=13))
    if until <= now:
        raise WpcUnavailable("synoptic_fronts_stale")
    iso = lambda t: t.isoformat().replace("+00:00", "Z")
    return {
        "capability": CAPABILITY,
        "id": hashlib.sha256(payload).hexdigest()[:24],
        "kind": "surface_analysis",
        "model": "NOAA WPC coded surface frontal analysis",
        "unit": "feature",
        "model_run": iso(valid),
        "analysis_time": iso(valid),
        "valid_at": iso(valid),
        "valid_until": iso(until),
        "refresh_after_seconds": 600,
        "quality_status": "verified",
        "availability_status": "available",
        "coverage": dict(COVERAGE),
        "geometry": {"type": "FeatureCollection", "features": features},
        "provenance": {
            "provider_id": "noaa_nws",
            "model": "NOAA WPC Surface Analysis",
            "source": "NOAA/NWS WPC coded_sfc bulletin",
            "attribution": "NOAA / NWS Weather Prediction Center",
            "data_origin": "human_analysis",
            "measurement_method": "official_encoded_front_vertices",
        },
    }


def clip_segment(start, end, bbox):
    """Return the exact portion of a linear lon/lat segment inside a rectangle."""
    x, y = start
    dx, dy = end[0] - x, end[1] - y
    if not dx and not dy:
        return None
    lower, upper = 0.0, 1.0
    for delta, distance in (
        (-dx, x - bbox["west"]), (dx, bbox["east"] - x),
        (-dy, y - bbox["south"]), (dy, bbox["north"] - y),
    ):
        if delta == 0:
            if distance < 0:
                return None
            continue
        fraction = distance / delta
        if delta < 0:
            lower = max(lower, fraction)
        else:
            upper = min(upper, fraction)
        if lower >= upper:
            return None
    def boundary(fraction):
        return [min(bbox["east"], max(bbox["west"], x + dx * fraction)),
                min(bbox["north"], max(bbox["south"], y + dy * fraction))]

    return [start if lower == 0 else boundary(lower),
            end if upper == 1 else boundary(upper)]


def clip_features(features, bbox):
    """Clip only to provider coverage, preserving source order and vertices."""
    result = []
    for feature in features:
        coords = feature["geometry"]["coordinates"]
        path = []
        for start, end in zip(coords, coords[1:]):
            segment = clip_segment(start, end, bbox)
            if segment is None or path and path[-1] != segment[0]:
                if path:
                    result.append({**feature, "geometry": {"type": "LineString", "coordinates": path}})
                path = []
            if segment is not None:
                if not path:
                    path.append(segment[0])
                path.append(segment[1])
        if path:
            result.append({**feature, "geometry": {"type": "LineString", "coordinates": path}})
    return result


def subset(frame: dict, bbox: dict) -> dict:
    boxes = (bbox,) if bbox["west"] <= bbox["east"] else (
        {**bbox, "east": 180.}, {**bbox, "west": -180.})
    selected = []
    for feature in clip_features(frame["geometry"]["features"], frame["coverage"]):
        coords = feature["geometry"]["coordinates"]
        if any(clip_segment(a, b, box) for box in boxes for a, b in zip(coords, coords[1:])):
            selected.append(feature)
    return {**frame, "availability_status": "available" if selected else "empty", "geometry":
            {"type": "FeatureCollection", "features": selected}}


def bulletin_candidates(index: bytes, base: str) -> list[str]:
    """The official archive uses extensionless codsusHH_hr names."""
    if len(index) > MAX_INDEX_BYTES:
        raise WpcUnavailable("synoptic_fronts_index_budget")
    page = Listing()
    try:
        page.feed(index.decode("utf-8"))
    except UnicodeError as error:
        raise WpcUnavailable("synoptic_fronts_invalid_index") from error
    names = {href for href in page.links if re.fullmatch(r"codsus(?:00|03|06|09|12|15|18|21)_hr", href)}
    return [urljoin(base, name) for name in sorted(names, reverse=True)]


def _unexpired(frame, now):
    return bool(frame and datetime.fromisoformat(frame["valid_until"]) > now)


async def _download(hass, url, size):
    async with asyncio.timeout(3):
        return await _fetch(hass, url, size)


async def async_fetch_fronts(hass, bbox):
    """Bounded independent fetch; provider failure cannot block ECCC/GFS."""
    from .const import DOMAIN
    request = normalize_bbox(bbox)
    if request is None or not bbox_overlaps(COVERAGE, request):
        raise WpcUnavailable("synoptic_fronts_no_coverage")
    state = hass.data.setdefault(DOMAIN, {}).setdefault(
        "synoptic_wpc_front_state",
        {"lock": asyncio.Lock(), "frame": None, "checked": 0.,
         "cooldown": 0., "error": None})
    now = datetime.now(timezone.utc)
    cached = state["frame"]
    if _unexpired(cached, now) and state["checked"] + 600 > monotonic():
        return subset(cached, request)
    if state["lock"].locked() and _unexpired(cached, now):
        return subset({**cached, "quality_status": "refreshing"}, request)
    async with state["lock"]:
        now = datetime.now(timezone.utc)
        cached = state["frame"]
        if _unexpired(cached, now) and state["checked"] + 600 > monotonic():
            return subset(cached, request)
        if state["cooldown"] > monotonic():
            if _unexpired(cached, now):
                return subset({**cached, "quality_status": "retained"}, request)
            raise WpcUnavailable(state["error"])
        received = False
        for day in (now.date(), (now - timedelta(days=1)).date()):
            base = ROOT + day.strftime("%Y%m%d") + "/"
            try:
                choices = bulletin_candidates(await _download(
                    hass, base, MAX_INDEX_BYTES), base)
                received = received or not choices
            except (WpcUnavailable, TimeoutError, OSError):
                continue
            for url in choices[:2]:
                try:
                    raw = await _download(hass, url, MAX_BULLETIN_BYTES)
                    received = True
                    frame = await hass.async_add_executor_job(
                        decode_fronts, raw, now)
                    if not _unexpired(cached, now) or frame["valid_at"] >= cached["valid_at"]:
                        state.update(frame=frame, checked=monotonic(),
                                     cooldown=0., error=None)
                        return subset(frame, request)
                except (WpcUnavailable, TimeoutError, OSError):
                    continue
        code = "synoptic_fronts_no_valid_data" if received else "synoptic_fronts_provider_unreachable"
        state.update(cooldown=monotonic() + 180, error=code)
        if _unexpired(cached, datetime.now(timezone.utc)):
            return subset({**cached, "quality_status": "retained"}, request)
        raise WpcUnavailable(code)
