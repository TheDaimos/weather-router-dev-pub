"""Bounded GRIB2 MSLP decoder with optional ECMWF ecCodes backend.

The module is safe to import on HA OS even when ecCodes is unavailable.
If ecCodes cannot load, numeric ICON/IFS products fail closed; existing NOAA
NetCDF fallback remains intact. No implicit installation or binary execution.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import math
from typing import Any

MAX_GRIB_BYTES = 18_000_000
MAX_SOURCE_POINTS = 5_000_000
MAX_GRID_NODES = 16_000


class GribPressureUnavailable(ValueError):
    """Stable pressure-model failure code."""


def _grib_time(day: Any, hhmm: Any) -> datetime:
    try:
        if type(day) not in (int, str) or type(hhmm) not in (int, str):
            raise ValueError("invalid")
        date = datetime.strptime(str(day), "%Y%m%d")
        hour, minute = divmod(int(hhmm), 100)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("invalid")
        return date.replace(hour=hour, minute=minute, tzinfo=timezone.utc)
    except ValueError as error:
        raise GribPressureUnavailable("synoptic_grib_invalid_time") from error


def regrid_scattered(
    latitudes, longitudes, values, plan: dict, *, run: datetime,
    valid: datetime, fingerprint: str, units: str = "Pa",
) -> dict:
    """Aggregate real model nodes onto a bounded regular 2-D pressure grid.

    Each output node is the mean of *actual local GRIB values*, not an
    interpolation invented across missing data. Empty cells are masked, not
    extrapolated. This coarse synoptic resampling loses subgrid detail and must
    never be labelled a native high-resolution ICON surface.
    """
    try:
        import numpy as np
    except ImportError as error:
        raise GribPressureUnavailable("synoptic_grib_numpy_unavailable") from error
    latitude = np.asarray(latitudes, dtype=np.float64)
    longitude = np.asarray(longitudes, dtype=np.float64)
    pressure = np.asarray(values, dtype=np.float64)
    if not (latitude.ndim == longitude.ndim == pressure.ndim == 1):
        raise GribPressureUnavailable("synoptic_grib_invalid_coordinates")
    count = len(pressure)
    if not 4 <= count <= MAX_SOURCE_POINTS or len(latitude) != count or len(longitude) != count:
        raise GribPressureUnavailable("synoptic_grib_source_grid_budget")
    if units in ("Pa", "pa"):
        pressure = pressure / 100.0
    elif units not in ("hPa", "mbar"):
        raise GribPressureUnavailable("synoptic_grib_pressure_unit_unverified")
    west = float(plan["west"])
    span = min(360.0, float(plan["east"]) - west)
    south, north = float(plan["south"]), float(plan["north"])
    if not (0 < span <= 360 and -90 <= south < north <= 90):
        raise GribPressureUnavailable("synoptic_grib_invalid_bbox")
    valid_values = (
        np.isfinite(latitude) & np.isfinite(longitude) & np.isfinite(pressure)
        & (latitude >= south) & (latitude <= north)
        & (pressure >= 870) & (pressure <= 1090)
    )
    # Coordinate unwrapping is anchored on the requested bbox, not the native
    # grid's 0/360 representation. At +180°, the periodic seam is explicit.
    east_distance = np.mod(longitude - west, 360.0)
    valid_values &= (east_distance <= span)
    if not np.any(valid_values):
        raise GribPressureUnavailable("synoptic_grib_outside_grid")
    x_pos = east_distance[valid_values]
    y_pos = latitude[valid_values]
    p = pressure[valid_values]
    # Larger bboxes downsample more coarsely. Global target ~2 degree;
    # bounded <16k cells, lower than native model precision by design.
    max_columns = 150
    max_rows = 90
    nx = max(3, min(max_columns, int(math.ceil(span / max(.25, .25*plan["stride"])))))
    ny = max(3, min(max_rows, int(math.ceil((north-south) / max(.25, .25*plan["stride"])))))
    if nx*ny + ny > MAX_GRID_NODES:
        raise GribPressureUnavailable("synoptic_grib_target_grid_budget")
    x_edges = np.linspace(0., span, nx+1)
    y_edges = np.linspace(south, north, ny+1)
    counts, _, _ = np.histogram2d(y_pos, x_pos, bins=(y_edges, x_edges))
    sums, _, _ = np.histogram2d(y_pos, x_pos, bins=(y_edges, x_edges), weights=p)
    good = counts >= 1.
    if np.count_nonzero(good) < 0.60*nx*ny:
        raise GribPressureUnavailable("synoptic_grib_incomplete_spatial_coverage")
    field = np.divide(sums, counts, out=np.zeros_like(sums), where=good)
    xs = [float(west+(i+.5)*span/nx) for i in range(nx)]
    ys = [float(south+(j+.5)*(north-south)/ny) for j in range(ny)]
    cyclic = bool(plan["cyclic"] and span >= 359.9 and
                  np.count_nonzero(good[:, 0] & good[:, -1]) >= .65*ny)
    if cyclic:
        xs.append(xs[0]+360.)
        field = np.column_stack((field, field[:, 0]))
        good = np.column_stack((good, good[:, 0]))
    return {
        "x": xs, "y": ys, "pressure_hpa": field.ravel().tolist(),
        "mask": good.astype("uint8").ravel().tolist(),
        "run": run, "valid": valid,
        "hash": fingerprint, "cyclic": cyclic,
        "native_source_nodes": count, "regridded_nodes": int(field.size),
        "resampling_method": "observed_model_cell_aggregation",
    }



def _icon_coordinates(eccodes, pressure_handle, sidecars: tuple[bytes, bytes]) -> tuple:
    """Verify native ICON CLAT/CLON are exactly on the pressure field's grid.

    GRIB2 unstructured ICON pressure messages intentionally omit geolocation.
    Real CLAT and CLON are additional official fields, on the *same* grid,
    same ordered cells, in degrees. Using a mismatched grid would silently
    displace every contour across the planet.
    """
    if not isinstance(sidecars, tuple) or len(sidecars) != 2:
        raise GribPressureUnavailable("synoptic_icon_missing_native_coordinates")
    expected = {}
    for key in ("numberOfPoints", "numberOfGridUsed", "uuidOfHGrid"):
        try:
            expected[key] = eccodes.codes_get(pressure_handle, key)
        except Exception as error:
            raise GribPressureUnavailable("synoptic_icon_missing_grid_identity") from error
    vectors = []
    for raw, expected_number in zip(sidecars, (1, 2)):
        if len(raw) < 16 or len(raw) > MAX_GRIB_BYTES or raw[:4] != b"GRIB":
            raise GribPressureUnavailable("synoptic_icon_invalid_coordinate_file")
        handle = None
        try:
            handle = eccodes.codes_new_from_message(raw)
            if (int(eccodes.codes_get(handle, "edition")) != 2
                    or int(eccodes.codes_get(handle, "totalLength")) != len(raw)):
                raise GribPressureUnavailable("synoptic_icon_coordinate_field_length")
            for key, val in expected.items():
                if eccodes.codes_get(handle, key) != val:
                    raise GribPressureUnavailable("synoptic_icon_coordinate_grid_mismatch")
            if (int(eccodes.codes_get(handle, "discipline")) != 0
                    or int(eccodes.codes_get(handle, "parameterCategory")) != 191
                    or int(eccodes.codes_get(handle, "parameterNumber")) != expected_number):
                raise GribPressureUnavailable("synoptic_icon_wrong_coordinate_parameter")
            unit = str(eccodes.codes_get(handle, "units")).lower()
            if unit not in ("deg", "degree", "degrees", "degrees_north",
                            "degrees_east", "degree north", "degree east"):
                raise GribPressureUnavailable("synoptic_icon_coordinate_units_unverified")
            vector = eccodes.codes_get_array(handle, "values")
            if len(vector) != int(expected["numberOfPoints"]):
                raise GribPressureUnavailable("synoptic_icon_coordinate_count_mismatch")
            vectors.append(vector)
        except GribPressureUnavailable:
            raise
        except Exception as error:
            raise GribPressureUnavailable("synoptic_icon_coordinate_decode_failed") from error
        finally:
            if handle is not None:
                eccodes.codes_release(handle)
    latitude, longitude = vectors
    if (not any(-90. <= x <= 90. for x in latitude)
            or not any(-180. <= x <= 360. for x in longitude)):
        raise GribPressureUnavailable("synoptic_icon_coordinate_values_invalid")
    return latitude, longitude


def decode_grib_pressure(
    raw: bytes, plan: dict, *, model: str,
    coordinate_fields: tuple[bytes, bytes] | None = None,
) -> dict:
    """Decode exactly one MSLP GRIB2 message through ecCodes in an executor."""
    if len(raw) < 16 or len(raw) > MAX_GRIB_BYTES or raw[:4] != b"GRIB":
        raise GribPressureUnavailable("synoptic_grib_transport_budget")
    if raw[7] != 2:
        raise GribPressureUnavailable("synoptic_grib_wrong_edition")
    try:
        import eccodes
    except (ImportError, OSError) as error:
        raise GribPressureUnavailable("synoptic_grib_eccodes_not_installed") from error
    handle = None
    try:
        handle = eccodes.codes_new_from_message(raw)
        if eccodes.codes_get(handle, "edition") != 2:
            raise GribPressureUnavailable("synoptic_grib_wrong_edition")
        if int(eccodes.codes_get(handle, "totalLength")) != len(raw):
            raise GribPressureUnavailable("synoptic_grib_multiple_or_truncated_fields")
        short = str(eccodes.codes_get(handle, "shortName")).lower()
        allowed = {"icon": {"prmsl", "msl", "pmsl"},
                   "icon-eu": {"prmsl", "msl", "pmsl"},
                   "ifs": {"msl", "prmsl"},
                   "fmi-meps": {"msl", "prmsl", "pmsl"}}
        if short not in allowed.get(model, set()):
            raise GribPressureUnavailable("synoptic_grib_not_mean_sea_level_pressure")
        unit = str(eccodes.codes_get(handle, "units"))
        if unit != "Pa":
            raise GribPressureUnavailable("synoptic_grib_unverified_units")
        level_type = str(eccodes.codes_get(handle, "typeOfLevel"))
        if level_type not in ("meanSea", "surface"):
            raise GribPressureUnavailable("synoptic_grib_wrong_level")
        run = _grib_time(eccodes.codes_get(handle, "dataDate"),
                         eccodes.codes_get(handle, "dataTime"))
        valid = _grib_time(eccodes.codes_get(handle, "validityDate"),
                           eccodes.codes_get(handle, "validityTime"))
        now = datetime.now(timezone.utc)
        if (run > now+timedelta(minutes=15) or now-run > timedelta(hours=30)
                or valid < run or abs((valid-now).total_seconds()) > 21600):
            raise GribPressureUnavailable("synoptic_grib_invalid_model_time")
        size = int(eccodes.codes_get(handle, "numberOfPoints"))
        if not 4 <= size <= MAX_SOURCE_POINTS:
            raise GribPressureUnavailable("synoptic_grib_source_grid_budget")
        # ecCodes can decode native unstructured ICON triangular grids,
        # ECMWF's reduced Gaussian grids and regular lat-lon grids equally.
        grid_type = str(eccodes.codes_get(handle, "gridType"))
        if grid_type == "unstructured_grid":
            if model not in ("icon", "icon-eu"):
                raise GribPressureUnavailable("synoptic_grib_unsupported_unstructured_grid")
            if coordinate_fields is None:
                raise GribPressureUnavailable("synoptic_icon_missing_native_coordinates")
            lats, lons = _icon_coordinates(eccodes, handle, coordinate_fields)
        elif grid_type in ("regular_ll", "reduced_gg", "regular_gg", "reduced_ll"):
            lats = eccodes.codes_get_array(handle, "latitudes")
            lons = eccodes.codes_get_array(handle, "longitudes")
        else:
            raise GribPressureUnavailable("synoptic_grib_unsupported_grid")
        values = eccodes.codes_get_array(handle, "values")
        if any(len(v) != size for v in (lats, lons, values)):
            raise GribPressureUnavailable("synoptic_grib_incoherent_nodes")
        return regrid_scattered(
            lats, lons, values, plan, run=run, valid=valid,
            fingerprint=hashlib.sha256(raw).hexdigest()[:24], units=unit)
    except GribPressureUnavailable:
        raise
    except (ValueError, RuntimeError, KeyError, TypeError, OverflowError) as error:
        raise GribPressureUnavailable("synoptic_grib_decode_failed") from error
    finally:
        if handle is not None:
            eccodes.codes_release(handle)


def contours_from_grib(raw: bytes, plan: dict, *, model: str,
                       provider_id: str, source: str, attribution: str,
                       coordinate_fields: tuple[bytes, bytes] | None = None) -> dict:
    from .synoptic_gfs import contours
    native = decode_grib_pressure(raw, plan, model=model,
                                  coordinate_fields=coordinate_fields)
    frame = contours(native)
    frame["model"] = {"icon": "DWD ICON Global",
                      "icon-eu": "DWD ICON-EU",
                      "ifs": "ECMWF IFS",
                      "fmi-meps": "FMI HARMONIE MEPS"}[model]
    frame["provenance"] = {
        "provider_id": provider_id, "model": frame["model"],
        "source": source, "attribution": attribution,
        "data_origin": "model",
        "measurement_method": "nwp_grib2_pressure_contours",
        "resampling_method": native["resampling_method"],
    }
    frame["delivery_diagnostics"]["native_nodes"] = native["native_source_nodes"]
    frame["delivery_diagnostics"]["regridded_nodes"] = native["regridded_nodes"]
    return frame
