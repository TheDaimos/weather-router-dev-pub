"""FMI HARMONIE/MEPS regional mean-sea-level pressure field and contours.

Official Binary Download service: query one Pressure surface model run, one
valid time and a bounded bbox. FMI catalog explicitly labels this parameter
'Mean Sea Level Pressure' for harmonie_scandinavia_surface.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from functools import partial
from time import monotonic
from typing import Any

from .synoptic_netcdf import contours_from_netcdf, NetcdfPressureUnavailable, MAX_NETCDF_BYTES
from .wind_field_source import plan_subset, WindFieldUnavailable

ENDPOINT = "https://data.fmi.fi/download"
MEPS = "harmonie_scandinavia_surface"
REGION = {"west": -25., "east": 57., "south": 45., "north": 80.}


class FmiPressureUnavailable(ValueError):
    """An official FMI binary product did not pass MSLP quality checks."""


def candidate_runs(now: datetime) -> list[tuple[datetime, datetime]]:
    """Past 6-hour model reference times with forecast valid near now."""
    base = now.replace(hour=(now.hour//6)*6, minute=0, second=0, microsecond=0)
    result = []
    for hours in (0, 6, 12, 18):
        run = base - timedelta(hours=hours)
        # Nearest current forecast hour, no predicted future for "latest".
        forecast = run + timedelta(hours=max(0, round((now-run).total_seconds()/3600)))
        if run <= now and forecast <= now+timedelta(minutes=35):
            result.append((run, forecast))
    return result


async def async_fetch_isobars(hass: Any, bbox: dict) -> dict:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .spatial_coverage import bbox_contains, normalize_bbox
    from .const import DOMAIN
    import aiohttp
    requested = normalize_bbox(bbox)
    if requested is None or not bbox_contains(REGION, requested):
        raise FmiPressureUnavailable("synoptic_fmi_outside_meps_region")
    try:
        plan = plan_subset(bbox)
    except WindFieldUnavailable as error:
        raise FmiPressureUnavailable("synoptic_fmi_invalid_bbox") from error
    key = tuple(plan.values())
    state = hass.data.setdefault(DOMAIN, {}).setdefault(
        "synoptic_fmi_pressure", {"lock": asyncio.Lock(), "cache": {},
                                 "cooldown": 0., "requests": 0, "failures": 0})
    now = datetime.now(timezone.utc)
    cached = state["cache"].get(key)
    if cached and cached[1] > monotonic() and datetime.fromisoformat(
            cached[0]["valid_until"].replace("Z", "+00:00")) > now:
        return cached[0]
    if state["cooldown"] > monotonic():
        raise FmiPressureUnavailable("synoptic_fmi_cooldown")
    async with state["lock"]:
        cached = state["cache"].get(key)
        if cached and cached[1] > monotonic():
            return cached[0]
        now = datetime.now(timezone.utc)
        last_code = "synoptic_fmi_no_valid_pressure_run"
        utc = lambda value: value.isoformat().replace("+00:00", "Z")
        # Grid resolution is separately bounded; do not request whole MEPS.
        xmin = max(-25., requested["west"]-1.)
        xmax = min(57., requested["east"]+1.)
        ymin = max(45., requested["south"]-1.)
        ymax = min(80., requested["north"]+1.)
        for run, valid in candidate_runs(now)[:3]:
            params = {
                "producer": MEPS, "param": "Pressure",
                "projection": "EPSG:4326", "format": "netcdf",
                "bbox": ",".join(str(x) for x in (xmin, ymin, xmax, ymax)),
                "gridsize": "120,80", "timesteps": "1",
                "origintime": utc(run), "starttime": utc(valid),
                "endtime": utc(valid),
            }
            state["requests"] += 1
            try:
                async with asyncio.timeout(28):
                    async with async_get_clientsession(hass).get(
                        ENDPOINT, params=params,
                        headers={"User-Agent": "WeatherRouter/0.10 (FMI MEPS MSL pressure)"},
                        allow_redirects=False,
                        timeout=aiohttp.ClientTimeout(total=25),
                    ) as response:
                        if response.status == 429:
                            raise FmiPressureUnavailable("synoptic_fmi_rate_limited")
                        if response.status != 200:
                            raise FmiPressureUnavailable("synoptic_fmi_source_http_error")
                        if response.content_length and response.content_length > MAX_NETCDF_BYTES:
                            raise FmiPressureUnavailable("synoptic_fmi_transport_budget")
                        raw = await response.content.read(MAX_NETCDF_BYTES+1)
                        if len(raw) > MAX_NETCDF_BYTES:
                            raise FmiPressureUnavailable("synoptic_fmi_transport_budget")
                job = partial(
                    contours_from_netcdf, raw, plan, model="FMI HARMONIE MEPS",
                    provider_id="fmi", source="FMI Binary Download / HARMONIE Pressure",
                    attribution="Finnish Meteorological Institute (FMI) · CC BY 4.0",
                    supplied_run=run)
                frame = await hass.async_add_executor_job(job)
                actual = datetime.fromisoformat(frame["model_run"].replace("Z","+00:00"))
                if abs((actual-run).total_seconds()) > 3600:
                    raise FmiPressureUnavailable("synoptic_fmi_model_run_mismatch")
                state["cache"][key] = (frame, monotonic()+600)
                while len(state["cache"]) > 3:
                    state["cache"].pop(next(iter(state["cache"])))
                state["cooldown"] = 0.
                return frame
            except (FmiPressureUnavailable, NetcdfPressureUnavailable, TimeoutError) as error:
                last_code = str(error)
                if last_code == "synoptic_fmi_rate_limited":
                    break
        state["failures"] += 1
        state["cooldown"] = monotonic()+150
        raise FmiPressureUnavailable(last_code)
