"""Bounded world-wide NOAA GFS mean-sea-level pressure and derived isobars.

Official numeric GFS field via Unidata NCSS. One native model time per response,
no mesh of point forecasts, no custom GRIB dependency and no drawing in HA loop.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import math
import struct
from time import monotonic

from .wind_field_source import ENDPOINT, MAX_NODES, WindFieldUnavailable, _cf_instant, plan_subset, utc
from .wind_netcdf import read_classic

CAPABILITY = "weather.synoptic.isobars"
FIELD = "Pressure_reduced_to_MSL_msl"
MAX_BYTES = 4_000_000
MAX_SEGMENTS = 20000
CONTOUR_INTERVAL_HPA = 4


class PressureUnavailable(ValueError):
    """Stable bounded GFS pressure failure."""


def decode_pressure(data: bytes, plan: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        values = read_classic(data)["variables"]
        variable = values[FIELD]
        axes = {value["attributes"].get("standard_name"): (name, value)
                for name, value in values.items() if value["attributes"].get("standard_name")}
        lat_key, lat = axes["latitude"]
        lon_key, lon = axes["longitude"]
        time_key, time_var = axes["time"]
        _, run_var = axes["forecast_reference_time"]
        if variable["dimensions"] != [time_key, lat_key, lon_key] or variable["shape"][0] != 1:
            raise PressureUnavailable("synoptic_gfs_invalid_grid")
        attrs = variable["attributes"]
        if attrs.get("units") != "Pa" or attrs.get("scale_factor", [1.]) != [1.] or attrs.get("add_offset", [0.]) != [0.]:
            raise PressureUnavailable("synoptic_gfs_invalid_pressure_units")
        if not {time_key, lat_key, lon_key}.issubset(set(attrs.get("coordinates", "").split())):
            raise PressureUnavailable("synoptic_gfs_invalid_coordinates")
        projection = values[attrs["grid_mapping"]]["attributes"]
        if projection.get("grid_mapping_name") != "latitude_longitude":
            raise PressureUnavailable("synoptic_gfs_invalid_crs")
        if lat["attributes"].get("units") != "degrees_north" or lon["attributes"].get("units") != "degrees_east":
            raise PressureUnavailable("synoptic_gfs_invalid_axes")
        run = _cf_instant(run_var)
        valid = _cf_instant(time_var)
        if (run > now + timedelta(minutes=10) or now - run > timedelta(hours=24)
                or abs((valid - now).total_seconds()) > 10800 or valid < run):
            raise PressureUnavailable("synoptic_gfs_invalid_model_time")
        center = (plan["west"] + plan["east"]) / 2
        xs = [((float(x) - center + 180) % 360) - 180 + center for x in lon["values"]]
        ys = list(map(float, lat["values"]))
        cols, rows = sorted(range(len(xs)), key=xs.__getitem__), sorted(range(len(ys)), key=ys.__getitem__)
        x = [xs[i] for i in cols]
        y = [ys[i] for i in rows]
        if len(x) < 2 or len(y) < 2 or len(x) * len(y) > MAX_NODES:
            raise PressureUnavailable("synoptic_gfs_grid_budget")
        for axis in (x, y):
            step = axis[1] - axis[0]
            if step <= 0 or not all(math.isfinite(z) for z in axis) or any(abs(b-a-step) > 0.00001 for a,b in zip(axis, axis[1:])):
                raise PressureUnavailable("synoptic_gfs_irregular_grid")
        if y[0] < -90 or y[-1] > 90:
            raise PressureUnavailable("synoptic_gfs_invalid_axes")
        data_hpa = []
        mask = []
        for row in rows:
            for col in cols:
                val = variable["values"][row*len(xs) + col]
                good = (math.isfinite(val) and 87000 <= val <= 109000
                        and all(val not in attrs.get(key, []) for key in ("_FillValue", "missing_value")))
                data_hpa.append(val/100 if good else 0.0)
                mask.append(1 if good else 0)
        if not any(mask):
            raise PressureUnavailable("synoptic_gfs_no_valid_cells")
        # Explicitly close a genuine global periodic longitude axis. Never join
        # unrelated edge columns just because a client requested a world bbox.
        cyclic = bool(plan["cyclic"] and abs(x[-1] - x[0] + x[1] - x[0] - 360) < 0.00001)
        if plan["cyclic"] and not cyclic:
            raise PressureUnavailable("synoptic_gfs_incomplete_global_grid")
        if cyclic:
            nx = len(x)
            for array in (data_hpa, mask):
                array[:] = [value for row in range(len(y))
                            for value in array[row*nx:(row+1)*nx] + [array[row*nx]]]
            x.append(x[0] + 360)
            if len(mask) > MAX_NODES:
                raise PressureUnavailable("synoptic_gfs_grid_budget")
        return {"x": x, "y": y, "pressure_hpa": data_hpa, "mask": mask,
                "cyclic": cyclic,
                "run": run, "valid": valid, "hash": hashlib.sha256(data).hexdigest()[:24]}
    except PressureUnavailable:
        raise
    except (WindFieldUnavailable, ValueError, KeyError, TypeError, IndexError, OverflowError, struct.error, UnicodeError) as error:
        raise PressureUnavailable("synoptic_gfs_invalid_native_contract") from error


def _interpolate(a, b, va, vb, level):
    fraction = (level-va)/(vb-va)
    return [round(a[0] + (b[0]-a[0])*fraction, 5),
            round(a[1] + (b[1]-a[1])*fraction, 5)]


def connect_segments(segments: list) -> list:
    """Stitch exact marching-squares endpoints into maximal contour polylines.

    Five-decimal vertices are shared by adjacent grid cells. The traversal
    stops at non-manifold junctions and preserves closed cycles. It never
    joins across missing cells, which have no generated edges.
    """
    edges = [(tuple(segment[0]), tuple(segment[1])) for segment in segments]
    incident = {}
    for index, (a, b) in enumerate(edges):
        incident.setdefault(a, []).append(index)
        incident.setdefault(b, []).append(index)
    visited = set()
    lines = []

    def walk(start, first):
        line = [list(start)]
        here, edge_id = start, first
        while edge_id not in visited:
            visited.add(edge_id)
            a, b = edges[edge_id]
            there = b if a == here else a
            line.append(list(there))
            if len(incident[there]) != 2:
                break
            rest = [i for i in incident[there] if i not in visited]
            if not rest:
                break
            here, edge_id = there, rest[0]
        if len(line) > 1:
            lines.append(line)

    # Open and branched contours before closed loops.
    for node, adj in incident.items():
        if len(adj) != 2:
            for edge_id in adj:
                if edge_id not in visited:
                    walk(node, edge_id)
    for edge_id, (start, _) in enumerate(edges):
        if edge_id not in visited:
            walk(start, edge_id)
    return lines


def contours(native: dict, now: datetime | None = None) -> dict:
    """Deterministic marching squares; ambiguous saddles are paired by centre value."""
    now = now or datetime.now(timezone.utc)
    x, y, pressure, mask = (native[key] for key in ("x", "y", "pressure_hpa", "mask"))
    nx, ny = len(x), len(y)
    good = [v for v,m in zip(pressure,mask) if m]
    lower = math.ceil(min(good) / CONTOUR_INTERVAL_HPA)*CONTOUR_INTERVAL_HPA
    upper = math.floor(max(good) / CONTOUR_INTERVAL_HPA)*CONTOUR_INTERVAL_HPA
    if upper - lower > 160:
        raise PressureUnavailable("synoptic_gfs_unphysical_pressure_range")
    levels = list(range(lower, upper+1, CONTOUR_INTERVAL_HPA))
    segments = 0
    features = []
    for level in levels:
        paths = []
        for row in range(ny-1):
            for col in range(nx-1):
                i = row*nx+col
                indices = (i, i+1, i+nx+1, i+nx)
                if not all(mask[index] for index in indices):
                    continue
                values = [pressure[index] for index in indices]
                # Half-open threshold prevents an identical grid vertex from being
                # assigned to both sides of the contour.
                above = [v >= level for v in values]
                if all(above) or not any(above):
                    continue
                vertices = ((x[col], y[row]), (x[col+1], y[row]),
                            (x[col+1], y[row+1]), (x[col], y[row+1]))
                crossing = [edge for edge in range(4) if above[edge] != above[(edge+1)%4]]
                if len(crossing) == 2:
                    pairs = [(crossing[0], crossing[1])]
                elif len(crossing) == 4:
                    # Asymptotic-decider-like centre split; exact saddle uses
                    # deterministic pairing. No arbitrary crossing intersections.
                    pairs = [(0, 1), (2, 3)] if sum(values)/4 >= level else [(0, 3), (1, 2)]
                else:
                    raise PressureUnavailable("synoptic_gfs_contour_topology")
                def point(edge):
                    j = (edge+1)%4
                    return _interpolate(vertices[edge], vertices[j], values[edge], values[j], level)
                for a,b in pairs:
                    p0, p1 = point(a), point(b)
                    if p0 != p1:
                        paths.append([p0,p1])
                        segments += 1
                        if segments > MAX_SEGMENTS:
                            raise PressureUnavailable("synoptic_gfs_contour_budget")
        if paths:
            # The renderer receives connected curves instead of tens of
            # thousands of independent two-point strokes.
            features.append({"type": "Feature",
                             "geometry": {"type": "MultiLineString",
                                          "coordinates": connect_segments(paths)},
                             "properties": {"pressure_hpa": level}})
    # A small, valid view may contain no 4-hPa crossing. Empty geometry is
    # still valid data, not a provider outage or a reason to switch models.
    valid = native["valid"]
    expiry = valid + timedelta(hours=3)
    # The declared forecast validity must outlast valid_at; the 30-minute
    # in-memory cache TTL is independent of the meteorological validity.
    if native["run"] > valid or expiry <= now:
        raise PressureUnavailable("synoptic_gfs_stale")
    return {
        "capability": CAPABILITY, "id": native["hash"], "kind": "model_forecast",
        "model": "NOAA GFS", "model_run": utc(native["run"]), "valid_at": utc(valid),
        "valid_until": utc(expiry), "refresh_after_seconds": 600,
        "unit": "hPa", "contour_interval_hpa": CONTOUR_INTERVAL_HPA,
        "geometry": {"type": "FeatureCollection", "features": features},
        "coverage": {"type": "bbox", "crs": "EPSG:4326",
                     "west": x[0], "east": x[-1], "south": y[0], "north": y[-1]},
        "provenance": {"provider_id": "noaa_nws", "model": "GFS",
                       "source": "NSF Unidata NCSS", "attribution": "NOAA / NCEP GFS · NSF Unidata / UCAR",
                       "data_origin": "model", "measurement_method": "nwp_derived_pressure_contours"},
        "delivery_diagnostics": {"nodes": len(mask), "line_segments": segments},
    }



def derived_centers(native: dict, now: datetime | None = None) -> dict:
    """Conservative model-derived extrema when official H/L vectors are absent.

    This is a lower-confidence fallback, not a substitute for a national
    meteorological surface analysis. The source and method remain explicit.
    """
    now = now or datetime.now(timezone.utc)
    x, y = native["x"], native["y"]
    p, valid_mask = native["pressure_hpa"], native["mask"]
    nx, ny = len(x), len(y)
    cyclic = native.get("cyclic", False)
    unique = nx-1 if cyclic else nx
    step = max(abs(x[1]-x[0]), abs(y[1]-y[0]))
    radius = max(2, min(6, math.ceil(2.0/max(step, 1e-6))))
    features = []
    picks = []
    if nx < 2*radius+1 or ny < 2*radius+1:
        return _center_frame(native, now, [])
    for row in range(radius, ny-radius):
        if abs(y[row]) >= 85:
            continue
        for col in range(unique if cyclic else radius, unique if cyclic else unique-radius):
            index = row*nx+col
            if not valid_mask[index]:
                continue
            neighbors = []
            ring = []
            complete = True
            for dr in range(-radius, radius+1):
                for dc in range(-radius, radius+1):
                    if not dr and not dc:
                        continue
                    cc = (col+dc)%unique if cyclic else col+dc
                    ii = (row+dr)*nx+cc
                    if not valid_mask[ii]:
                        complete = False
                        break
                    value = p[ii]
                    neighbors.append(value)
                    if abs(dr) == radius or abs(dc) == radius:
                        ring.append(value)
                if not complete:
                    break
            if not complete or not neighbors:
                continue
            value = p[index]
            high = value > max(neighbors) and value - sum(ring)/len(ring) >= 2.5
            low = value < min(neighbors) and sum(ring)/len(ring) - value >= 2.5
            if not high and not low:
                continue
            lon = (x[col]+180)%360-180
            lat = y[row]
            score = (value - sum(ring)/len(ring)) if high else (sum(ring)/len(ring)-value)
            picks.append((score, "H" if high else "L", lon, lat, value))
    # Strongest local extrema win; adjacent artifacts cannot become multiple
    # 'H'/'L' glyphs for the same meteorological structure.
    retained = []
    for score, kind, lon, lat, value in sorted(picks, reverse=True):
        if len(retained) >= 200:
            break
        def km(other):
            o_lon, o_lat = other[2], other[3]
            dlat = math.radians(lat-o_lat)
            dlon = math.radians((lon-o_lon+180)%360-180)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat))*math.cos(math.radians(o_lat))*math.sin(dlon/2)**2
            return 2*6371*math.asin(min(1.0, math.sqrt(a)))
        if any(other[1] == kind and km(other) < 350 for other in retained):
            continue
        retained.append((score, kind, lon, lat, value))
        features.append({"type": "Feature",
                         "geometry": {"type": "Point",
                                      "coordinates": [round(lon,5),round(lat,5)]},
                         "properties": {"kind": kind, "pressure_hpa": round(value,1),
                                        "detection": "conservative_model_extremum"}})
    return _center_frame(native, now, features)


def _center_frame(native: dict, now: datetime, features: list) -> dict:
    valid = native["valid"]
    expires = valid + timedelta(hours=3)
    if native["run"] > valid or expires <= now:
        raise PressureUnavailable("synoptic_gfs_stale")
    return {
        "capability": "weather.synoptic.pressure_centers",
        "id": native["hash"] + "-extrema", "kind": "model_forecast",
        "model": "NOAA GFS", "model_run": utc(native["run"]),
        "valid_at": utc(valid), "valid_until": utc(expires),
        "refresh_after_seconds": 600, "unit": "hPa",
        "geometry": {"type": "FeatureCollection", "features": features},
        "coverage": {"type": "bbox", "crs": "EPSG:4326",
                     "west": native["x"][0], "east": native["x"][-1],
                     "south": native["y"][0], "north": native["y"][-1]},
        "provenance": {"provider_id": "noaa_nws", "model": "GFS",
                       "source": "NSF Unidata NCSS",
                       "attribution": "NOAA / NCEP GFS · NSF Unidata / UCAR",
                       "data_origin": "model",
                       "measurement_method": "nwp_derived_pressure_extrema",
                       "confidence": "provisional_model_extrema"},
    }


async def async_fetch_centers(hass, bbox):
    """Independent global GFS alternative if ECCC official centres fail."""
    from .const import DOMAIN
    try:
        key = tuple(plan_subset(bbox).values())
    except WindFieldUnavailable as error:
        raise PressureUnavailable("synoptic_invalid_bbox") from error
    state = hass.data.setdefault(DOMAIN, {}).get("synoptic_isobar_state", {})
    native_entry = state.get("native_cache", {}).get(key)
    if native_entry is None or native_entry[1] <= monotonic():
        # When upgrading from an older module state, an isobar frame may still
        # be cached without its underlying native grid. Do not treat that as
        # a source failure: force a fresh bounded numeric fetch.
        state.get("cache", {}).pop(key, None)
        await async_fetch_isobars(hass, bbox)
        state = hass.data.setdefault(DOMAIN, {}).get("synoptic_isobar_state", {})
        native_entry = state.get("native_cache", {}).get(key)
    if native_entry is None or native_entry[1] <= monotonic():
        raise PressureUnavailable("synoptic_gfs_native_cache_unavailable")
    return await hass.async_add_executor_job(derived_centers, native_entry[0])


async def async_fetch_isobars(hass, bbox):
    """Bounded, coalesced and cached contour frame per canonical bbox."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .const import DOMAIN
    try:
        plan = plan_subset(bbox)
    except WindFieldUnavailable as error:
        raise PressureUnavailable("synoptic_invalid_bbox") from error
    state = hass.data.setdefault(DOMAIN, {}).setdefault("synoptic_isobar_state", {
        "lock": asyncio.Lock(), "cache": {}, "native_cache": {},
        "cooldown": 0.0, "requests": 0, "failures": 0})
    key = tuple(plan.values())
    now = datetime.now(timezone.utc)
    entry = state["cache"].get(key)
    if entry and entry[1] > monotonic() and datetime.fromisoformat(entry[0]["valid_until"].replace("Z", "+00:00")) > max(now, datetime.fromisoformat(entry[0]["valid_at"].replace("Z", "+00:00"))):
        return entry[0]
    async with state["lock"]:
        now = datetime.now(timezone.utc)
        entry = state["cache"].get(key)
        if entry and entry[1] > monotonic() and datetime.fromisoformat(entry[0]["valid_until"].replace("Z", "+00:00")) > max(now, datetime.fromisoformat(entry[0]["valid_at"].replace("Z", "+00:00"))):
            return entry[0]
        if monotonic() < state["cooldown"]:
            raise PressureUnavailable("synoptic_gfs_cooldown")
        params = [("var", FIELD), ("time", "present"), ("accept", "netcdf3"),
                  ("horizStride", str(plan["stride"]))]
        params += [(name, str(plan[name])) for name in ("west", "east", "south", "north")]
        state["requests"] += 1
        try:
            async with asyncio.timeout(32):
                async with async_get_clientsession(hass).get(
                        ENDPOINT, params=params, timeout=28,
                        headers={"User-Agent": "WeatherRouter/0.10 (personal research visualization)"}) as response:
                    if response.status in (429, 503):
                        raise PressureUnavailable("synoptic_gfs_overloaded")
                    if response.status != 200:
                        raise PressureUnavailable("synoptic_gfs_http_error")
                    if response.content_length and response.content_length > MAX_BYTES:
                        raise PressureUnavailable("synoptic_gfs_transport_budget")
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        raw.extend(chunk)
                        if len(raw) > MAX_BYTES:
                            raise PressureUnavailable("synoptic_gfs_transport_budget")
            native = await hass.async_add_executor_job(decode_pressure, bytes(raw), plan)
            frame = await hass.async_add_executor_job(contours, native)
            state.setdefault("native_cache", {})[key] = (native, monotonic() + 600)
            while len(state["native_cache"]) > 4:
                state["native_cache"].pop(next(iter(state["native_cache"])))
            state["cache"][key] = (frame, monotonic() + 600)
            while len(state["cache"]) > 4:
                state["cache"].pop(next(iter(state["cache"])))
            return frame
        except (PressureUnavailable, TimeoutError) as error:
            state["failures"] += 1
            state["cooldown"] = monotonic() + 60
            if isinstance(error, PressureUnavailable):
                raise
            raise PressureUnavailable("synoptic_gfs_timeout") from error
        except Exception as error:
            state["failures"] += 1
            state["cooldown"] = monotonic() + 60
            raise PressureUnavailable("synoptic_gfs_unavailable") from error
