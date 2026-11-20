"""MET Norway MET-Nordic / MEPS synoptic MSLP from a bounded THREDDS subset.

Official NetCDF product:
https://thredds.met.no/thredds/dodsC/metpplatest/
 met_forecast_1_0km_nordic_latest.nc
The corresponding TDS NCSS subset URL is used only if the server advertises
and supports it; no whole-Nordic 1-km NetCDF is downloaded to Home Assistant.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from functools import partial
from time import monotonic
from typing import Any

from .synoptic_netcdf import contours_from_netcdf, NetcdfPressureUnavailable, MAX_NETCDF_BYTES
from .wind_field_source import plan_subset, WindFieldUnavailable

ENDPOINT = ("https://thredds.met.no/thredds/ncss/grid/metpplatest/"
            "met_forecast_1_0km_nordic_latest.nc")
# Officially documented regional MEPS model as a secondary source. Both
# endpoints share a provider and may share a model family: NOT independent NWP.
MEPS_ENDPOINT = ("https://thredds.met.no/thredds/ncss/grid/meps25files/"
                 "meps_det_pp_2_5km_latest.nc")
# These are merely cheap preliminary routing bounds, NOT hard provider coverage
# claims. Actual NetCDF geolocation and complete field cells are mandatory.
NORDIC_WINDOW = {"west": -20., "east": 55., "south": 48., "north": 85.}


class MetPressureUnavailable(ValueError):
    """A regional model source could not produce verified MSLP geometry."""


async def async_fetch_isobars(hass: Any, bbox: dict) -> dict:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .spatial_coverage import bbox_contains, normalize_bbox
    from .const import DOMAIN
    import aiohttp
    requested = normalize_bbox(bbox)
    if requested is None or not bbox_contains(NORDIC_WINDOW, requested):
        raise MetPressureUnavailable("synoptic_met_outside_nordic_model")
    try:
        plan = plan_subset(bbox)
    except WindFieldUnavailable as error:
        raise MetPressureUnavailable("synoptic_met_invalid_bbox") from error
    key = tuple(plan.values())
    state = hass.data.setdefault(DOMAIN, {}).setdefault(
        "synoptic_met_pressure", {"lock": asyncio.Lock(), "cache": {},
                                 "cooldown": 0., "requests": 0, "failures": 0})
    entry = state["cache"].get(key)
    now = datetime.now(timezone.utc)
    if entry and entry[1] > monotonic() and datetime.fromisoformat(
            entry[0]["valid_until"].replace("Z", "+00:00")) > now:
        return entry[0]
    if state["cooldown"] > monotonic():
        raise MetPressureUnavailable("synoptic_met_cooldown")
    async with state["lock"]:
        now = datetime.now(timezone.utc)
        entry = state["cache"].get(key)
        if entry and entry[1] > monotonic():
            return entry[0]
        # The 1-km original mesh is never downloaded wholesale. If the NCSS
        # route does not expose this product, the officially documented MEPS
        # dataset is attempted separately, with the same strict model QA.
        stride = max(8, plan["stride"] * 10)
        params = {
            "var": "air_pressure_at_sea_level",
            "north": str(min(85, requested["north"]+1)),
            "south": str(max(48, requested["south"]-1)),
            "west": str(max(-20, requested["west"]-1)),
            "east": str(min(55, requested["east"]+1)),
            "horizStride": str(stride), "time": "present",
            "accept": "netcdf3",
        }
        last_code = "synoptic_met_no_verified_regional_pressure"
        for endpoint, model in (
            (ENDPOINT, "MET Nordic / 1-km"),
            (MEPS_ENDPOINT, "MET MEPS / 2.5-km"),
        ):
            state["requests"] += 1
            try:
                async with asyncio.timeout(14):
                    async with async_get_clientsession(hass).get(
                        endpoint, params=params,
                        headers={"User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos)"},
                        allow_redirects=False,
                        timeout=aiohttp.ClientTimeout(total=12),
                    ) as response:
                        if response.status in (429, 503):
                            raise MetPressureUnavailable("synoptic_met_source_busy")
                        if response.status != 200:
                            raise MetPressureUnavailable("synoptic_met_ncss_unavailable")
                        if response.content_length and response.content_length > MAX_NETCDF_BYTES:
                            raise MetPressureUnavailable("synoptic_met_response_budget")
                        raw = await response.content.read(MAX_NETCDF_BYTES + 1)
                        if len(raw) > MAX_NETCDF_BYTES:
                            raise MetPressureUnavailable("synoptic_met_response_budget")
                job = partial(
                    contours_from_netcdf, raw, plan, model=model,
                    provider_id="met_norway", source="MET Norway THREDDS NCSS / CF NetCDF",
                    attribution="Meteorologisk institutt (MET Norway) · CC BY 4.0")
                frame = await hass.async_add_executor_job(job)
                state["cache"][key] = (frame, monotonic()+600)
                while len(state["cache"]) > 3:
                    state["cache"].pop(next(iter(state["cache"])))
                state["cooldown"] = 0.
                return frame
            except (MetPressureUnavailable, NetcdfPressureUnavailable, TimeoutError) as error:
                last_code = str(error) if isinstance(error, ValueError) else "synoptic_met_timeout"
                if last_code == "synoptic_met_source_busy":
                    break
        state["failures"] += 1
        state["cooldown"] = monotonic()+150
        raise MetPressureUnavailable(last_code)

