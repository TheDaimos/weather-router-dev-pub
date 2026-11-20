"""SMHI SNOW1G true model-grid MSLP contours using official MultiPoint API.

The JSON forecast publishes one actual pressure value per real grid coordinate.
We never infer pressure from sparse point forecasts or reconstruct a fictitious
regional model outside the official geometry.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from functools import partial
import hashlib
import json
import math
from time import monotonic
from typing import Any

from .synoptic_grib import regrid_scattered, GribPressureUnavailable
from .synoptic_gfs import contours
from .wind_field_source import plan_subset, WindFieldUnavailable

ROOT = "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1"
PARAM = "air_pressure_at_mean_sea_level"
MAX_META = 130_000
MAX_GEOMETRY = 24_000_000
MAX_FORECAST = 8_000_000
MAX_POINTS = 600_000
REGION = {"west": -23., "east": 48., "south": 45., "north": 80.}


class SmhiPressureUnavailable(ValueError):
    """SMHI data failed pressure-grid, model-time or geography checks."""


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise SmhiPressureUnavailable("synoptic_smhi_missing_time")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError("naive")
        return instant.astimezone(timezone.utc)
    except ValueError as error:
        raise SmhiPressureUnavailable("synoptic_smhi_invalid_time") from error


def select_time(payload: bytes, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    try:
        times = json.loads(payload)["time"]
        if not isinstance(times, list) or not 1 <= len(times) <= 300:
            raise ValueError("times")
        stamps = [parse_time(item) for item in times]
    except (ValueError, KeyError, TypeError) as error:
        raise SmhiPressureUnavailable("synoptic_smhi_invalid_time_catalog") from error
    candidate = min(stamps, key=lambda value: abs((value-now).total_seconds()))
    if abs((candidate-now).total_seconds()) > 5*3600:
        raise SmhiPressureUnavailable("synoptic_smhi_stale_forecast")
    return candidate


def verify_parameter(raw: bytes) -> bool:
    """Confirm sea-level pressure as a declared hPa model parameter."""
    try:
        items = json.loads(raw)["parameter"]
        if not isinstance(items, list):
            raise ValueError("parameter")
        return any(
            item.get("name") == PARAM and item.get("unit") == "hPa"
            and item.get("levelType") == "hmsl"
            for item in items if isinstance(item, dict))
    except (ValueError, KeyError, TypeError):
        return False


def decode(geo_raw: bytes, field_raw: bytes, plan: dict, now=None) -> dict:
    """Validate matching complete coordinate/value indexes, then derive lines."""
    import numpy as np
    now = now or datetime.now(timezone.utc)
    try:
        geo = json.loads(geo_raw)
        field = json.loads(field_raw)
        if geo.get("type") != "MultiPoint" or not isinstance(geo.get("coordinates"), list):
            raise ValueError("geometry")
        coordinates = geo["coordinates"]
        if not 10 <= len(coordinates) <= MAX_POINTS:
            raise ValueError("count")
        series = field["timeSeries"]
        if not isinstance(series, list) or len(series) != 1:
            raise ValueError("series")
        entry = series[0]
        run = parse_time(field["referenceTime"])
        valid = parse_time(entry["time"])
        values = entry["data"][PARAM]
        if not isinstance(values, list) or len(values) != len(coordinates):
            raise ValueError("index")
        points = np.asarray(coordinates, dtype=float)
        p = np.asarray(values, dtype=float)
        if points.ndim != 2 or points.shape[1] < 2:
            raise ValueError("point shape")
        if (not np.all(np.isfinite(points[:, :2]))
                or np.any(np.abs(points[:, 1]) > 90)
                or np.any(np.abs(points[:, 0]) > 360)):
            raise ValueError("geo")
        if run > valid or run > now + timedelta(minutes=15) or now-run > timedelta(hours=36):
            raise ValueError("run")
        if abs((valid-now).total_seconds()) > 5*3600:
            raise ValueError("valid")
        # SMHI declares 9999 as its missing-value sentinel.
        p[(p == 9999) | (p < 870) | (p > 1090)] = np.nan
        if np.count_nonzero(np.isfinite(p)) < len(p)*.60:
            raise ValueError("field missing")
    except (TypeError, ValueError, KeyError, OverflowError) as error:
        raise SmhiPressureUnavailable("synoptic_smhi_invalid_grid") from error
    try:
        native = regrid_scattered(
            points[:, 1], points[:, 0], p, plan,
            run=run, valid=valid,
            fingerprint=hashlib.sha256(field_raw).hexdigest()[:24],
            units="hPa")
        frame = contours(native, now)
    except GribPressureUnavailable as error:
        raise SmhiPressureUnavailable(str(error)) from error
    frame["model"] = "SMHI SNOW1G"
    frame["provenance"] = {
        "provider_id": "smhi", "model": "SNOW1G",
        "source": "SMHI SNOW1G MultiPoint pressure MSL",
        "attribution": "Swedish Meteorological and Hydrological Institute (SMHI)",
        "data_origin": "model",
        "measurement_method": "official_gridded_mslp_json_contours",
        "resampling_method": native["resampling_method"],
    }
    frame["delivery_diagnostics"]["native_nodes"] = len(p)
    frame["delivery_diagnostics"]["regridded_nodes"] = native["regridded_nodes"]
    return frame


async def _json(hass, url, max_bytes):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    import aiohttp
    if not url.startswith(ROOT+"/"):
        raise SmhiPressureUnavailable("synoptic_smhi_invalid_url")
    async with asyncio.timeout(23):
        async with async_get_clientsession(hass).get(
            url, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=20),
            headers={"Accept-Encoding": "gzip", "Accept": "application/json",
                     "User-Agent": "WeatherRouter/0.10 (SMHI pressure synoptic)"}
        ) as response:
            if response.status != 200:
                raise SmhiPressureUnavailable("synoptic_smhi_http_unavailable")
            if response.content_length and response.content_length > max_bytes:
                raise SmhiPressureUnavailable("synoptic_smhi_transport_budget")
            data = await response.content.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise SmhiPressureUnavailable("synoptic_smhi_transport_budget")
            return data


async def async_fetch_isobars(hass: Any, bbox: dict) -> dict:
    from .const import DOMAIN
    from .spatial_coverage import bbox_contains, normalize_bbox
    request = normalize_bbox(bbox)
    if request is None or not bbox_contains(REGION, request):
        raise SmhiPressureUnavailable("synoptic_smhi_outside_region")
    try:
        plan = plan_subset(bbox)
    except WindFieldUnavailable as error:
        raise SmhiPressureUnavailable("synoptic_smhi_invalid_bbox") from error
    key = tuple(plan.values())
    state = hass.data.setdefault(DOMAIN, {}).setdefault(
        "synoptic_smhi_pressure", {"lock": asyncio.Lock(),
            "cache": {}, "geometry": None, "geometry_until": 0.,
            "parameter_ok_until": 0., "cooldown": 0., "requests": 0,
            "failures": 0})
    now = datetime.now(timezone.utc)
    entry = state["cache"].get(key)
    if entry and entry[1] > monotonic() and datetime.fromisoformat(
            entry[0]["valid_until"].replace("Z", "+00:00")) > now:
        return entry[0]
    if state["cooldown"] > monotonic():
        raise SmhiPressureUnavailable("synoptic_smhi_cooldown")
    async with state["lock"]:
        now = datetime.now(timezone.utc)
        entry = state["cache"].get(key)
        if entry and entry[1] > monotonic():
            return entry[0]
        try:
            if state["parameter_ok_until"] < monotonic():
                state["requests"] += 1
                if not verify_parameter(await _json(hass, ROOT+"/parameter.json", MAX_META)):
                    raise SmhiPressureUnavailable("synoptic_smhi_parameter_not_mslp")
                state["parameter_ok_until"] = monotonic() + 21600
            if state["geometry_until"] < monotonic() or state["geometry"] is None:
                state["requests"] += 1
                state["geometry"] = await _json(
                    hass, ROOT+"/geotype/multipoint.json", MAX_GEOMETRY)
                state["geometry_until"] = monotonic() + 21600
            state["requests"] += 1
            latest = select_time(await _json(hass, ROOT+"/times.json", MAX_META), now)
            stamp = latest.strftime("%Y%m%dT%H%M%SZ")
            endpoint = (ROOT+"/geotype/multipoint/time/"+stamp+"/parameter/"
                        +PARAM+"/data.json?with-geo=false&downsample=1")
            state["requests"] += 1
            raw = await _json(hass, endpoint, MAX_FORECAST)
            task = partial(decode, state["geometry"], raw, plan, now=now)
            frame = await hass.async_add_executor_job(task)
            state["cache"][key] = (frame, monotonic()+600)
            while len(state["cache"]) > 2:
                state["cache"].pop(next(iter(state["cache"])))
            state["cooldown"] = 0.
            return frame
        except (SmhiPressureUnavailable, TimeoutError, OSError) as error:
            state["failures"] += 1
            state["cooldown"] = monotonic()+180
            raise SmhiPressureUnavailable(str(error)) from error
