"""ECMWF IFS global MSL pressure contours from a verified single GRIB2 byte range.

No invented full-dataset endpoints. ECMWF .index supplies exact field offsets;
the official GRIB service MUST return HTTP 206 with matching Content-Range.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import partial
import importlib.util
from time import monotonic
from typing import Any

from .wind_field_source import plan_subset, WindFieldUnavailable
from .synoptic_grib import contours_from_grib, GribPressureUnavailable, MAX_GRIB_BYTES


class EcmwfPressureUnavailable(ValueError):
    """Stable pressure-source unavailable code."""


async def _fetch_range(hass, url: str, start: int, size: int) -> bytes:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    import aiohttp
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "data.ecmwf.int"
            or not parsed.path.startswith("/forecasts/")
            or not parsed.path.endswith(".grib2")
            or parsed.query or parsed.fragment):
        raise EcmwfPressureUnavailable("synoptic_ecmwf_invalid_source_url")
    if not 0 <= start <= 500_000_000 or not 16 <= size <= 8_000_000:
        raise EcmwfPressureUnavailable("synoptic_ecmwf_field_budget")
    end = start + size - 1
    async with asyncio.timeout(24):
        async with async_get_clientsession(hass).get(
            url,
            headers={"Range": f"bytes={start}-{end}",
                     "Accept": "application/octet-stream",
                     "User-Agent": "WeatherRouter/0.10 (ECMWF IFS MSL data)"},
            allow_redirects=False, timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status != 206:
                raise EcmwfPressureUnavailable("synoptic_ecmwf_range_not_honored")
            claimed = response.headers.get("Content-Range", "")
            if not claimed.startswith(f"bytes {start}-{end}/"):
                raise EcmwfPressureUnavailable("synoptic_ecmwf_wrong_content_range")
            payload = await response.content.read(size + 1)
            if len(payload) != size or payload[:4] != b"GRIB":
                raise EcmwfPressureUnavailable("synoptic_ecmwf_invalid_grib")
            return payload


async def async_fetch_isobars(hass: Any, bbox: dict) -> dict:
    from .const import DOMAIN
    from .providers.ecmwf_open_data import _probe_mslp_field, _PORTAL
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    if importlib.util.find_spec("eccodes") is None:
        raise EcmwfPressureUnavailable("synoptic_grib_eccodes_not_installed")
    try:
        plan = plan_subset(bbox)
    except WindFieldUnavailable as error:
        raise EcmwfPressureUnavailable("synoptic_ecmwf_invalid_bbox") from error
    key = tuple(plan.values())
    state = hass.data.setdefault(DOMAIN, {}).setdefault(
        "synoptic_ecmwf_isobars", {"lock": asyncio.Lock(), "cache": {},
                                  "cooldown": 0., "requests": 0, "failures": 0})
    entry = state["cache"].get(key)
    now = datetime.now(timezone.utc)
    if entry and entry[1] > monotonic() and datetime.fromisoformat(
            entry[0]["valid_until"].replace("Z", "+00:00")) > now:
        return entry[0]
    if state["cooldown"] > monotonic():
        raise EcmwfPressureUnavailable("synoptic_ecmwf_cooldown")
    async with state["lock"]:
        now = datetime.now(timezone.utc)
        entry = state["cache"].get(key)
        if entry and entry[1] > monotonic():
            return entry[0]
        try:
            probe = await _probe_mslp_field(async_get_clientsession(hass), now)
            if probe.get("ok") is not True:
                raise EcmwfPressureUnavailable("synoptic_ecmwf_no_valid_index")
            raw = await _fetch_range(
                hass, _PORTAL + probe["grib_path"],
                probe["range_start"], probe["range_length"])
            task = partial(
                contours_from_grib, raw, plan,
                model="ifs", provider_id="ecmwf_open_data",
                source="ECMWF IFS Open Data / indexed MSL GRIB2",
                attribution="ECMWF Open Data · CC BY 4.0")
            frame = await hass.async_add_executor_job(task)
            # GRIB must match both the indexed model run and forecast step.
            model_run = datetime.fromisoformat(frame["model_run"].replace("Z", "+00:00"))
            valid = datetime.fromisoformat(frame["valid_at"].replace("Z", "+00:00"))
            indexed_valid = datetime.fromisoformat(probe["valid_at"].replace("Z", "+00:00"))
            if model_run.strftime("%Y%m%dT%HZ") != probe["run"]:
                raise EcmwfPressureUnavailable("synoptic_ecmwf_run_mismatch")
            if valid != indexed_valid:
                raise EcmwfPressureUnavailable("synoptic_ecmwf_step_mismatch")
            state["cache"][key] = (frame, monotonic()+600)
            while len(state["cache"]) > 4:
                state["cache"].pop(next(iter(state["cache"])))
            state["cooldown"] = 0.
            state["requests"] += 1
            return frame
        except (EcmwfPressureUnavailable, GribPressureUnavailable, TimeoutError) as error:
            state["failures"] += 1
            state["cooldown"] = monotonic()+90
            raise EcmwfPressureUnavailable(str(error)) from error
