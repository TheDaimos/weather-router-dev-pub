"""Bounded native NOAA GFS 10 m U/V subsets, delivered by Unidata NCSS.

No point-query mesh, image decoding, persistent buffer or native dependency.
This optional NOAA capability is independent of its regional NWS point API.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import math
import re
import struct
from time import monotonic

from .wind_netcdf import read_classic

CAPABILITY = "weather.wind.field_10m"
ENDPOINT = "https://thredds.ucar.edu/thredds/ncss/grid/grib/NCEP/GFS/Global_0p25deg/Best"
U_NAME = "u-component_of_wind_height_above_ground"
V_NAME = "v-component_of_wind_height_above_ground"
MAX_NODES = 16000
MAX_BYTES = 4_000_000


class WindFieldUnavailable(ValueError):
    """Stable, secret-safe provider failure."""


def utc(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def plan_subset(bbox):
    """One canonical request for all world copies; at most 16k delivered nodes."""
    if not isinstance(bbox, dict) or set(bbox) != {"west", "east", "south", "north"}:
        raise WindFieldUnavailable("wind_invalid_bbox")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in bbox.values()):
        raise WindFieldUnavailable("wind_invalid_bbox")
    west, east, south, north = (bbox[k] for k in ("west", "east", "south", "north"))
    if not -90 <= south < north <= 90 or abs(west) > 100000 or abs(east) > 100000:
        raise WindFieldUnavailable("wind_invalid_bbox")
    span = east - west
    if span <= 0:
        span %= 360
    if span <= 0:
        raise WindFieldUnavailable("wind_invalid_bbox")
    span = min(360, span)
    west = (west + 180) % 360 - 180
    # Reserve room for the boundary halo and the cyclic closing column.
    stride = max(1, math.ceil(max(span / .25 / 150, (north - south) / .25 / 90,
                                 math.sqrt(span * (north - south) / .25**2 / 12000))))
    step = .25 * stride
    full = span + 2 * step >= 360
    if full:
        west, east = -180., 180.
    else:
        west = math.floor(west / step) * step - step
        east = math.ceil((west + step + span) / step) * step + step
        if east - west >= 360:
            west, east, full = -180., 180., True
    # NCSS treats an exactly complete source box as "no spatial subset" and
    # ignores horizStride. Avoid that path; pole coverage remains explicit.
    south = max(-89.75, math.floor(south / step) * step - step)
    north = min(89.75, math.ceil(north / step) * step + step)
    return {"west": west, "east": east, "south": south, "north": north,
            "stride": stride, "cyclic": full}


def _cf_instant(var):
    attrs, values = var["attributes"], var["values"]
    if attrs.get("calendar", "standard") not in ("standard", "gregorian", "proleptic_gregorian"):
        raise WindFieldUnavailable("wind_unsupported_calendar")
    match = re.fullmatch(r"(Hour|hours?|minutes?|seconds?|days?) since (.+)", attrs.get("units", ""), re.I)
    if not match or len(values) != 1 or not math.isfinite(values[0]):
        raise WindFieldUnavailable("wind_invalid_time")
    base = datetime.fromisoformat(match[2].replace("Z", "+00:00"))
    if base.tzinfo is None:
        raise WindFieldUnavailable("wind_ambiguous_time")
    factor = {"h": 3600, "m": 60, "s": 1, "d": 86400}[match[1][0].lower()]
    return base.astimezone(timezone.utc) + timedelta(seconds=values[0] * factor)


def decode_field(data, plan, now=None):
    """Validate one coherent CF time/height/grid and preserve numeric U/V."""
    now = now or datetime.now(timezone.utc)
    try:
        variables = read_classic(data)["variables"]
    except (ValueError, IndexError, struct.error, UnicodeError) as error:
        raise WindFieldUnavailable("wind_invalid_native_format") from error
    try:
        u, v = variables[U_NAME], variables[V_NAME]
        axes = {x["attributes"].get("standard_name"): (name, x)
                for name, x in variables.items() if x["attributes"].get("standard_name")}
        lat_name, lat = axes["latitude"]
        lon_name, lon = axes["longitude"]
        time_name, time = axes["time"]
        ref_name, ref = axes["forecast_reference_time"]
        if u["dimensions"] != v["dimensions"] or u["shape"] != v["shape"]:
            raise WindFieldUnavailable("wind_incoherent_components")
        if len(lat["dimensions"]) != 1 or len(lon["dimensions"]) != 1 or u["dimensions"][-2:] != [lat["dimensions"][0], lon["dimensions"][0]] or u["shape"][:-2] != [1, 1]:
            raise WindFieldUnavailable("wind_unsupported_grid")
        time_dim, height_dim = u["dimensions"][:2]
        height = variables[height_dim]
        if time_dim != time_name or height["values"] != [10.] or height["attributes"].get("units") != "m":
            raise WindFieldUnavailable("wind_wrong_height_or_time")
        for component in (u, v):
            attrs = component["attributes"]
            if attrs.get("scale_factor", [1.]) != [1.] or attrs.get("add_offset", [0.]) != [0.]:
                raise WindFieldUnavailable("wind_unsupported_packed_values")
            if attrs.get("units") not in ("m/s", "m s-1") or attrs.get("grid_mapping") != u["attributes"].get("grid_mapping"):
                raise WindFieldUnavailable("wind_incoherent_units_or_projection")
            if not {time_name, ref_name, height_dim, lat_name, lon_name}.issubset(set(attrs.get("coordinates", "").split())):
                raise WindFieldUnavailable("wind_incoherent_coordinates")
        projection = variables[u["attributes"]["grid_mapping"]]["attributes"]
        if projection.get("grid_mapping_name") != "latitude_longitude":
            raise WindFieldUnavailable("wind_unsupported_projection")
        if lat["attributes"].get("units") != "degrees_north" or lon["attributes"].get("units") != "degrees_east":
            raise WindFieldUnavailable("wind_invalid_axes")
        valid, run = _cf_instant(time), _cf_instant(ref)
        # This policy applies only to this new native model field, never to rasters.
        if run > now + timedelta(minutes=10) or now - run > timedelta(hours=24) or abs((valid - now).total_seconds()) > 10800 or valid < run:
            raise WindFieldUnavailable("wind_model_time_unavailable")
        center = (plan["west"] + plan["east"]) / 2
        xs = [((float(x) - center + 180) % 360) - 180 + center for x in lon["values"]]
        ys = list(map(float, lat["values"]))
        cols, rows = sorted(range(len(xs)), key=xs.__getitem__), sorted(range(len(ys)), key=ys.__getitem__)
        x, y = [xs[i] for i in cols], [ys[i] for i in rows]
        if min(len(x), len(y)) < 2 or len(x) * len(y) > MAX_NODES:
            raise WindFieldUnavailable("wind_grid_budget")
        for axis in (x, y):
            step = axis[1] - axis[0]
            if step <= 0 or any(not math.isfinite(a) for a in axis) or any(abs((b-a)-step) > 1e-5 for a, b in zip(axis, axis[1:])):
                raise WindFieldUnavailable("wind_irregular_axes")
        if y[0] < -90 or y[-1] > 90:
            raise WindFieldUnavailable("wind_invalid_axes")
        def missing(component, value):
            attrs = component["attributes"]
            return not math.isfinite(value) or any(value in attrs.get(k, []) for k in ("_FillValue", "missing_value"))
        out_u, out_v, mask = [], [], []
        for row in rows:
            for col in cols:
                index = row * len(xs) + col
                a, b = u["values"][index], v["values"][index]
                ok = not missing(u, a) and not missing(v, b)
                out_u.append(a if ok else 0.)
                out_v.append(b if ok else 0.)
                mask.append(1 if ok else 0)
        cyclic = plan["cyclic"] and abs(x[-1] - x[0] + x[1] - x[0] - 360) < 1e-5
        if plan["cyclic"] and not cyclic:
            raise WindFieldUnavailable("wind_incomplete_global_grid")
        if cyclic:
            width = len(x)
            for array in (out_u, out_v, mask):
                array[:] = [value for row in range(len(y)) for value in
                            array[row * width:(row+1) * width] + [array[row * width]]]
            x.append(x[0] + 360)
        if len(mask) > MAX_NODES or not any(mask):
            raise WindFieldUnavailable("wind_no_valid_nodes")
        expiry = min(now + timedelta(minutes=30), valid + timedelta(hours=3), run + timedelta(hours=24))
        if expiry <= now:
            raise WindFieldUnavailable("wind_model_time_unavailable")
        return {"id": hashlib.sha256(data).hexdigest()[:24], "capability": CAPABILITY,
                "unit": "m/s", "height_m": 10, "model": "NOAA GFS", "kind": "model_forecast",
                "model_run": utc(run), "valid_at": utc(valid), "valid_until": utc(expiry),
                "refresh_after_seconds": max(30, min(900, int((expiry-now).total_seconds()))),
                "native_resolution_degrees": .25, "temporal_resolution_seconds": None,
                "model_output_interval_seconds": 3600, "model_cycle_seconds": 21600,
                "temporal_sampling": "one_native_valid_time_no_temporal_interpolation",
                "grid": {"crs": "EPSG:4326", "layout": "row_major_south_first", "latitudes": y,
                         "longitudes": x, "u": out_u, "v": out_v, "valid_mask": mask, "cyclic": cyclic},
                "coverage": {"west": x[0], "east": x[-1], "south": y[0], "north": y[-1]},
                "provenance": {"provider_id": "noaa_nws", "model": "GFS", "delivery": "Unidata NCSS",
                               "attribution": "NOAA / NCEP GFS · NSF Unidata / UCAR",
                               "source_url": "https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/gfs.php",
                               "delivery_url": "https://www.unidata.ucar.edu/", "license": "NOAA public-domain data; Unidata research service",
                               "data_origin": "model", "measurement_method": "numerical_model"}}
    except (KeyError, IndexError, TypeError, OverflowError) as error:
        raise WindFieldUnavailable("wind_invalid_native_contract") from error


def _retry_delay(value):
    try:
        return min(3600, max(30, int(value)))
    except (ValueError, TypeError):
        try:
            return min(3600, max(30, int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())))
        except (ValueError, TypeError, OverflowError):
            return 60


def _cached_subset(state, bbox, plan):
    """Reuse one authorized coherent frame; never assemble model generations."""
    exact = tuple(plan.values())
    keys = ([exact] if exact in state["cache"] else []) + [key for key in reversed(state["cache"]) if key != exact]
    now, tick = datetime.now(timezone.utc), monotonic()
    span = bbox["east"] - bbox["west"]
    if span <= 0:
        span %= 360
    span = min(360, span)
    west = (bbox["west"] + 180) % 360 - 180
    for key in keys:
        frame = state["cache"][key]
        if datetime.fromisoformat(frame["valid_until"].replace("Z", "+00:00")) <= now:
            continue
        if tick >= state["cooldown"] and tick - state.get(("fetched", key), 0) >= 900:
            continue
        if key == exact:
            return key, frame, "exact"
        grid = frame["grid"]
        xs, ys = grid["longitudes"], grid["latitudes"]
        if max(xs[1]-xs[0], ys[1]-ys[0]) > .25 * plan["stride"] + 1e-6:
            continue
        if bbox["south"] < ys[0] - 1e-6 or bbox["north"] > ys[-1] + 1e-6:
            continue
        shift = 360 * round(((xs[0]+xs[-1])/2 - (west+span/2)) / 360)
        if grid.get("cyclic") or west + shift >= xs[0] - 1e-6 and west + span + shift <= xs[-1] + 1e-6:
            return key, frame, "coverage"
    return None


def _cache_delivery(frame, state, kind):
    """Additive delivery diagnostics; authorization and cached payload stay immutable."""
    return {**frame, "delivery_diagnostics": {
        "cache": kind, "cache_hits": state["cache_hits"],
        "coverage_hits": state.get("coverage_hits", 0), "cache_misses": state.get("cache_misses", 0),
        "coalesced": state.get("coalesced", 0), "evictions": state.get("evictions", 0),
        "cache_entries": len(state["cache"]), "cache_limit": 6,
        "estimated_cache_bytes": sum((len(item["grid"]["u"]) + len(item["grid"]["v"])) * 32 + len(item["grid"]["valid_mask"]) * 8 for item in state["cache"].values()),
        "upstream_requests": state["requests"], "active_downloads": state["active"],
        "last_fetch_ms": state.get("last_fetch_ms"), "last_prepare_ms": state.get("last_prepare_ms")}}


async def async_fetch_native(hass, bbox):
    """Shared bounded cache/coalescing, one upstream transport, provider cooldown."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .const import DOMAIN
    from .diagnostic_center import record_http_exchange
    plan = plan_subset(bbox)
    state = hass.data.setdefault(DOMAIN, {}).setdefault("wind_field_runtime", {
        "cache": OrderedDict(), "inflight": {}, "slot": asyncio.Semaphore(1), "cooldown": 0.,
        "requests": 0, "cache_hits": 0, "failures": 0, "active": 0})
    key = tuple(plan.values())
    now = datetime.now(timezone.utc)
    for old_key, frame in list(state["cache"].items()):
        if datetime.fromisoformat(frame["valid_until"].replace("Z", "+00:00")) <= now:
            state["cache"].pop(old_key)
            state.pop(("fetched", old_key), None)
    cached = _cached_subset(state, bbox, plan)
    # Refresh native fields every 15 min, but reuse authorized values while upstream cools down.
    if cached:
        cache_key, frame, kind = cached
        state["cache_hits"] += 1
        if kind == "coverage":
            state["coverage_hits"] = state.get("coverage_hits", 0) + 1
        state["cache"].move_to_end(cache_key)
        return _cache_delivery(frame, state, kind)
    state["cache_misses"] = state.get("cache_misses", 0) + 1
    if key in state["inflight"]:
        state["coalesced"] = state.get("coalesced", 0) + 1
        frame, kind = await asyncio.shield(state["inflight"][key])
        return _cache_delivery(frame, state, "coalesced" if kind == "miss" else kind)
    if len(state["inflight"]) >= 3:
        raise WindFieldUnavailable("wind_transport_busy")

    async def fetch():
        async with state["slot"]:
            # A containing subset may have completed while this request waited.
            warm = _cached_subset(state, bbox, plan)
            if warm:
                cache_key, frame, kind = warm
                state["cache_hits"] += 1
                state["coverage_hits"] = state.get("coverage_hits", 0) + (kind == "coverage")
                state["cache"].move_to_end(cache_key)
                return frame, "coverage_after_wait" if kind == "coverage" else "exact_after_wait"
            if monotonic() < state["cooldown"]:
                raise WindFieldUnavailable("wind_provider_cooldown")
            params = [("var", U_NAME), ("var", V_NAME), ("time", "present"), ("vertCoord", "10"),
                      ("accept", "netcdf3"), ("horizStride", str(plan["stride"]))]
            params += [(name, str(plan[name])) for name in ("west", "east", "south", "north")]
            started, status = monotonic(), None
            state["requests"] += 1
            state["active"] += 1
            try:
                async with async_get_clientsession(hass).get(ENDPOINT, params=params, timeout=28,
                        headers={"User-Agent": "WeatherRouter/0.10 (personal research visualization)"}) as response:
                    status = response.status
                    if status in (429, 503):
                        state["cooldown"] = monotonic() + _retry_delay(response.headers.get("Retry-After"))
                        raise WindFieldUnavailable("wind_provider_overloaded")
                    if status in (401, 403):
                        raise WindFieldUnavailable("wind_source_access_denied")
                    if status != 200:
                        raise WindFieldUnavailable("wind_source_http_error")
                    if response.content_length and response.content_length > MAX_BYTES:
                        raise WindFieldUnavailable("wind_transport_budget")
                    payload = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        payload.extend(chunk)
                        if len(payload) > MAX_BYTES:
                            raise WindFieldUnavailable("wind_transport_budget")
                state["last_fetch_ms"] = round((monotonic() - started) * 1000, 3)
                preparing = monotonic()
                frame = await hass.async_add_executor_job(decode_field, bytes(payload), plan)
                state["last_prepare_ms"] = round((monotonic() - preparing) * 1000, 3)
                state["cache"][key] = frame
                state[("fetched", key)] = monotonic()
                while len(state["cache"]) > 6:
                    old_key, _ = state["cache"].popitem(last=False)
                    state.pop(("fetched", old_key), None)
                    state["evictions"] = state.get("evictions", 0) + 1
                record_http_exchange(hass, "noaa_nws", started_monotonic=started, http_status=status,
                                     declared_response_bytes=len(payload))
                return frame, "miss"
            except Exception as error:
                state["failures"] += 1
                if not isinstance(error, WindFieldUnavailable) or status is None or (status and status >= 500):
                    state["cooldown"] = max(state["cooldown"], monotonic() + 60)
                record_http_exchange(hass, "noaa_nws", started_monotonic=started, http_status=status, failed=True)
                if isinstance(error, WindFieldUnavailable):
                    raise
                raise WindFieldUnavailable("wind_source_timeout" if isinstance(error, TimeoutError) else "wind_source_unavailable") from error
            finally:
                state["active"] -= 1
    task = hass.async_create_task(fetch())
    state["inflight"][key] = task
    try:
        frame, kind = await asyncio.shield(task)
        return _cache_delivery(frame, state, kind)
    finally:
        # Keep coalescing a task even when an individual consumer disconnects.
        def complete(done):
            if state["inflight"].get(key) is done:
                state["inflight"].pop(key, None)
            if not done.cancelled():
                done.exception()
        if task.done():
            complete(task)
        else:
            task.add_done_callback(complete)
