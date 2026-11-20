"""World-wide ECCC GDPS ready-made high/low centre feed (not SWOB point pressure).

No inferred GeoJSON pressure semantics: fail closed when the publisher changes keys.
The only remote host and path are derived from the official MSC Datamart contract.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from time import monotonic
from typing import Any

CAPABILITY = "weather.synoptic.pressure_centers"
BASE = "https://dd.weather.gc.ca/today/model_gdps/15km"
MAX_BYTES = 1_500_000
MAX_FEATURES = 3500


class SynopticUnavailable(ValueError):
    """A stable, secret-free unavailable reason."""


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def candidates(now: datetime) -> list[tuple[datetime, int, str]]:
    """Latest UTC model cycles with native 3-hour lead nearest to current time."""
    now = now.astimezone(timezone.utc)
    cycles = []
    for offset in (0, 12, 24, 36):
        run = (now.replace(hour=0, minute=0, second=0, microsecond=0)
               + timedelta(hours=12 if now.hour >= 12 else 0)
               - timedelta(hours=offset))
        lead = max(0, int((now - run).total_seconds() // 10800) * 3)
        if run > now or lead > 240:
            continue
        stamp = run.strftime("%Y%m%dT%HZ")
        filename = f"{stamp}_MSC_GDPS_HighLowPressure_MSL_LatLon0.15_PT{lead:03d}H.json"
        url = f"{BASE}/{run:%H}/{lead:03d}/{filename}"
        cycles.append((run, lead, url))
    return cycles[:3]


def _name(properties: dict) -> str | None:
    for key in ("type", "Type", "center_type", "centre_type", "pressure_type",
                "high_low", "highLow", "highLowType", "symbol", "label", "name"):
        value = properties.get(key)
        if not isinstance(value, str):
            continue
        word = value.strip().casefold()
        if word in ("high", "h", "high pressure", "high-pressure", "anticyclone"):
            return "H"
        if word in ("low", "l", "low pressure", "low-pressure", "cyclone"):
            return "L"
    return None


def _pressure(properties: dict) -> float | None:
    for key in ("pressure_hpa", "pressureHpa", "pressure", "Pressure", "value",
                "Value", "mslp", "MSLP", "hpa", "hPa"):
        value = properties.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        try:
            number = float(value)
        except ValueError:
            continue
        if math.isfinite(number) and 870 <= number <= 1090:
            return round(number, 1)
    return None


def normalize(payload: bytes, run: datetime, lead: int, now: datetime | None = None) -> dict:
    """Strict, bounded raw GeoJSON -> stable WR centres. No guessed units."""
    if not payload or len(payload) > MAX_BYTES:
        raise SynopticUnavailable("synoptic_centers_transport_budget")
    try:
        raw = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as error:
        raise SynopticUnavailable("synoptic_centers_invalid_json") from error
    if not isinstance(raw, dict) or raw.get("type") != "FeatureCollection":
        raise SynopticUnavailable("synoptic_centers_not_geojson")
    crs = raw.get("crs")
    if crs is not None and crs not in ({"type": "name", "properties": {"name": "EPSG:4326"}},
                                      {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}):
        raise SynopticUnavailable("synoptic_centers_unknown_crs")
    features = raw.get("features")
    if not isinstance(features, list) or not 1 <= len(features) <= MAX_FEATURES:
        raise SynopticUnavailable("synoptic_centers_invalid_feature_count")
    valid = run + timedelta(hours=lead)
    now = now or datetime.now(timezone.utc)
    if run > now + timedelta(minutes=15) or now - run > timedelta(hours=48) or abs((valid-now).total_seconds()) > 21600:
        raise SynopticUnavailable("synoptic_centers_invalid_model_time")
    cleaned = []
    for item in features:
        if not isinstance(item, dict) or item.get("type") != "Feature":
            raise SynopticUnavailable("synoptic_centers_invalid_feature")
        geo = item.get("geometry")
        props = item.get("properties")
        if not isinstance(geo, dict) or geo.get("type") != "Point" or not isinstance(props, dict):
            raise SynopticUnavailable("synoptic_centers_invalid_geometry")
        coord = geo.get("coordinates")
        if (not isinstance(coord, list) or len(coord) < 2
                or any(type(v) not in (float, int) or not math.isfinite(v) for v in coord[:2])):
            raise SynopticUnavailable("synoptic_centers_invalid_coordinates")
        lon, lat = coord[:2]
        if not (-180 <= lon <= 360 and -90 <= lat <= 90):
            raise SynopticUnavailable("synoptic_centers_invalid_coordinates")
        kind, pressure = _name(props), _pressure(props)
        # Unknown metadata must never be misrepresented as real H/L centres.
        if kind is None or pressure is None:
            raise SynopticUnavailable("synoptic_centers_unknown_properties")
        lon = (lon + 180) % 360 - 180
        cleaned.append({"type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                        "properties": {"kind": kind, "pressure_hpa": pressure}})
    if not cleaned:
        raise SynopticUnavailable("synoptic_centers_empty")
    return {
        "capability": CAPABILITY, "id": hashlib.sha256(payload).hexdigest()[:24],
        "kind": "model_forecast", "model": "ECCC GDPS", "unit": "hPa",
        "model_run": utc(run), "valid_at": utc(valid),
        "valid_until": utc(min(now + timedelta(minutes=30), valid + timedelta(hours=6))),
        "refresh_after_seconds": 600,
        "geometry": {"type": "FeatureCollection", "features": cleaned},
        "coverage": {"type": "global", "crs": "EPSG:4326"},
        "provenance": {"provider_id": "eccc_geomet", "model": "GDPS",
                       "data_product": "HighLowPressure_MSL",
                       "attribution": "Environment and Climate Change Canada / MSC",
                       "source": "MSC Datamart", "data_origin": "model",
                       "measurement_method": "nwp_precomputed_centres"},
    }


def subset(frame: dict, bbox: dict) -> dict:
    west, east, south, north = (bbox[k] for k in ("west", "east", "south", "north"))
    span = east - west
    if span <= 0:
        span %= 360
    span = min(360, span)
    west = (west + 180) % 360 - 180
    features = [feature for feature in frame["geometry"]["features"]
                if south <= feature["geometry"]["coordinates"][1] <= north
                and ((feature["geometry"]["coordinates"][0] - west) % 360 <= span
                     or span == 360)]
    return {**frame, "geometry": {"type": "FeatureCollection", "features": features}}


async def async_fetch_centers(hass: Any, bbox: dict) -> dict:
    """One bounded authoritative global GDPS frame; lazy, coalesced and cacheable."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .const import DOMAIN
    state = hass.data.setdefault(DOMAIN, {}).setdefault("synoptic_centers_state", {
        "lock": asyncio.Lock(), "frame": None, "checked_at": 0.0, "cooldown": 0.0,
        "requests": 0, "failures": 0})
    now_tick = monotonic()
    cached = state["frame"]
    if (cached and now_tick - state["checked_at"] < 600
            and datetime.fromisoformat(cached["valid_until"].replace("Z", "+00:00")) > datetime.now(timezone.utc)):
        return subset(cached, bbox)
    async with state["lock"]:
        now_tick = monotonic()
        cached = state["frame"]
        if (cached and now_tick - state["checked_at"] < 600
                and datetime.fromisoformat(cached["valid_until"].replace("Z", "+00:00")) > datetime.now(timezone.utc)):
            return subset(cached, bbox)
        if now_tick < state["cooldown"]:
            if cached and datetime.fromisoformat(cached["valid_until"].replace("Z", "+00:00")) > datetime.now(timezone.utc):
                return subset(cached, bbox)
            raise SynopticUnavailable("synoptic_centers_cooldown")
        now = datetime.now(timezone.utc)
        last_error = "synoptic_centers_source_unavailable"
        for run, lead, url in candidates(now):
            state["requests"] += 1
            try:
                async with asyncio.timeout(12):
                    async with async_get_clientsession(hass).get(
                            url, allow_redirects=False, timeout=10,
                            headers={"User-Agent": "WeatherRouter/0.10 (Home Assistant; synoptic research)",
                                     "Accept": "application/geo+json, application/json"}) as response:
                        if response.status in (429, 503):
                            last_error = "synoptic_centers_source_overloaded"
                            break
                        if response.status != 200:
                            last_error = "synoptic_centers_source_http_error"
                            continue
                        if response.content_length and response.content_length > MAX_BYTES:
                            raise SynopticUnavailable("synoptic_centers_transport_budget")
                        payload = bytearray()
                        async for chunk in response.content.iter_chunked(65536):
                            payload.extend(chunk)
                            if len(payload) > MAX_BYTES:
                                raise SynopticUnavailable("synoptic_centers_transport_budget")
                frame = await hass.async_add_executor_job(normalize, bytes(payload), run, lead)
                if datetime.fromisoformat(frame["valid_until"].replace("Z", "+00:00")) <= now:
                    last_error = "synoptic_centers_stale"
                    continue
                state.update(frame=frame, checked_at=monotonic(), cooldown=0.)
                return subset(frame, bbox)
            except (SynopticUnavailable, TimeoutError) as error:
                last_error = str(error) if isinstance(error, SynopticUnavailable) else "synoptic_centers_timeout"
            except Exception:
                last_error = "synoptic_centers_transport_error"
        state["failures"] += 1
        state["cooldown"] = monotonic() + 60
        if cached and datetime.fromisoformat(cached["valid_until"].replace("Z", "+00:00")) > now:
            return subset(cached, bbox)
        raise SynopticUnavailable(last_error)
