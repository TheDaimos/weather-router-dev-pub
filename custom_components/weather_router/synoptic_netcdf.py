"""Regional, bounded CF NetCDF MSLP decoder (MET Norway and FMI).

Only explicit 2-D longitude/latitude arrays (or CF coordinate axes) and
verified sea-level pressure parameters are eligible for synoptic contours.
Never turn generic station/surface pressure into mean-sea-level isobars.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any
import re

from .synoptic_grib import regrid_scattered, GribPressureUnavailable

MAX_NETCDF_BYTES = 9_000_000
MAX_NETCDF_NODES = 300_000


class NetcdfPressureUnavailable(ValueError):
    """FMI/MET gridded pressure payload cannot be used safely."""


def _attr(value):
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="strict")
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, (list, tuple)) and len(value) == 1:
        return _attr(value[0])
    return value


def _cf_time(values, units: str):
    """Return UTC instants from a CF time axis with an explicit UTC origin."""
    import numpy as np
    if not isinstance(units, str):
        raise NetcdfPressureUnavailable("synoptic_netcdf_missing_time_units")
    match = re.fullmatch(
        r"(seconds?|minutes?|hours?|days?) since (\d{4}-\d\d-\d\d"
        r"[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?: Z|Z| ?\+00:?00)?)", units,
        flags=re.I)
    if not match:
        raise NetcdfPressureUnavailable("synoptic_netcdf_unsupported_time_axis")
    origin_text = (match.group(2).strip().replace(" ", "T", 1)
                   .replace(" +", "+").replace("Z", "+00:00"))
    try:
        base = datetime.fromisoformat(origin_text)
    except ValueError as error:
        raise NetcdfPressureUnavailable("synoptic_netcdf_invalid_time") from error
    if base.tzinfo is None:
        # CF 'since 1970-01-01 00:00:00' convention represents UTC.
        base = base.replace(tzinfo=timezone.utc)
    base = base.astimezone(timezone.utc)
    coefficient = {"s": 1., "m": 60., "h": 3600., "d": 86400.}[match.group(1)[0].lower()]
    result = []
    for number in np.asarray(values).flatten():
        try:
            result.append(base + timedelta(seconds=float(number)*coefficient))
        except (OverflowError, ValueError) as error:
            raise NetcdfPressureUnavailable("synoptic_netcdf_invalid_time") from error
    return result


def _read_variables(raw: bytes) -> dict:
    """Materialize an already transport-bounded NetCDF payload."""
    import numpy as np
    if raw[:4] in (b"CDF\x01", b"CDF\x02"):
        from .wind_netcdf import read_classic
        content = read_classic(raw)["variables"]
        return {
            name: {"data": np.asarray(item["values"]).reshape(item["shape"]),
                   "attrs": {k: _attr(v) for k, v in item["attributes"].items()},
                   "dims": item["dimensions"]}
            for name, item in content.items()
        }
    if raw[:8] != b"\x89HDF\r\n\x1a\n":
        raise NetcdfPressureUnavailable("synoptic_netcdf_wrong_format")
    try:
        import h5py
    except ImportError as error:
        raise NetcdfPressureUnavailable("synoptic_netcdf_h5py_unavailable") from error
    with h5py.File(BytesIO(raw), "r") as file:
        datasets = {}
        def visitor(name, item):
            if isinstance(item, h5py.Dataset):
                short = name.rsplit("/", 1)[-1]
                # Short names must be unique for the pressure/coordinate contract.
                if short not in datasets and short in (
                    "air_pressure_at_sea_level", "air_pressure_at_mean_sea_level",
                    "Pressure", "pressure_msl", "latitude", "longitude",
                    "lat", "lon", "time", "forecast_reference_time", "analysis_time",
                ):
                    if item.size > MAX_NETCDF_NODES*24:
                        raise NetcdfPressureUnavailable("synoptic_netcdf_node_budget")
                    datasets[short] = {
                        "data": item[()],
                        "attrs": {k: _attr(v) for k, v in item.attrs.items()},
                        "dims": [],
                    }
        file.visititems(visitor)
        return datasets


def decode_netcdf_pressure(raw: bytes, plan: dict, *, model: str,
                           supplied_run: datetime | None = None) -> dict:
    """Produce one conservative regular-grid native field from CF metadata."""
    import hashlib
    import numpy as np
    if not 32 <= len(raw) <= MAX_NETCDF_BYTES:
        raise NetcdfPressureUnavailable("synoptic_netcdf_transport_budget")
    v = _read_variables(raw)
    pressure_name = next((key for key in (
        "air_pressure_at_sea_level", "air_pressure_at_mean_sea_level",
        "pressure_msl", "Pressure") if key in v), None)
    if pressure_name is None:
        raise NetcdfPressureUnavailable("synoptic_netcdf_no_msl_pressure")
    source = v[pressure_name]
    units = _attr(source["attrs"].get("units"))
    if units not in ("Pa", "pa", "hPa", "mbar"):
        raise NetcdfPressureUnavailable("synoptic_netcdf_unverified_msl_units")
    if pressure_name == "Pressure":
        # FMI's named HARMONIE parameter "Pressure" is MSLP according
        # to its official Open Data parameter registry. Every other
        # generic Pressure field remains ambiguous and unusable.
        if model not in ("fmi-meps", "FMI HARMONIE MEPS"):
            raise NetcdfPressureUnavailable("synoptic_netcdf_ambiguous_pressure")
        stated = str(source["attrs"].get("standard_name") or "").lower()
        if stated and stated not in (
                "air_pressure_at_mean_sea_level",
                "air_pressure_at_sea_level"):
            raise NetcdfPressureUnavailable("synoptic_netcdf_wrong_pressure_reference")
    lat_key = "latitude" if "latitude" in v else "lat"
    lon_key = "longitude" if "longitude" in v else "lon"
    if lat_key not in v or lon_key not in v:
        raise NetcdfPressureUnavailable("synoptic_netcdf_missing_geolocation")
    y = np.asarray(v[lat_key]["data"], dtype=float)
    x = np.asarray(v[lon_key]["data"], dtype=float)
    values = np.asarray(source["data"], dtype=float)
    if values.ndim == 4 and values.shape[1] == 1:
        values = values[:, 0]
    reference = None
    if "forecast_reference_time" in v:
        item = v["forecast_reference_time"]
        timed = _cf_time(item["data"], item["attrs"].get("units", ""))
        if len(timed) == 1:
            reference = timed[0]
    elif "analysis_time" in v:
        item = v["analysis_time"]
        timed = _cf_time(item["data"], item["attrs"].get("units", ""))
        if len(timed) == 1:
            reference = timed[0]
    if reference is None:
        reference = supplied_run
    if reference is None or reference.tzinfo is None:
        raise NetcdfPressureUnavailable("synoptic_netcdf_missing_model_run")
    reference = reference.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if reference > now+timedelta(minutes=15) or now-reference > timedelta(hours=32):
        raise NetcdfPressureUnavailable("synoptic_netcdf_stale_run")
    if "time" not in v:
        raise NetcdfPressureUnavailable("synoptic_netcdf_missing_valid_time")
    time_var = v["time"]
    times = _cf_time(time_var["data"], time_var["attrs"].get("units", ""))
    if not times:
        raise NetcdfPressureUnavailable("synoptic_netcdf_empty_time_axis")
    selected = min(range(len(times)), key=lambda index: abs((times[index]-now).total_seconds()))
    valid = times[selected]
    if (valid < reference or abs((valid-now).total_seconds()) > 21600):
        raise NetcdfPressureUnavailable("synoptic_netcdf_invalid_forecast_time")
    if values.ndim == 3 and values.shape[0] == len(times):
        values = values[selected]
    if values.ndim != 2:
        raise NetcdfPressureUnavailable("synoptic_netcdf_unsupported_shape")
    if x.ndim == y.ndim == 1:
        if values.shape != (len(y), len(x)):
            raise NetcdfPressureUnavailable("synoptic_netcdf_wrong_axis_shape")
        x, y = np.meshgrid(x, y)
    elif x.shape != y.shape or y.shape != values.shape:
        raise NetcdfPressureUnavailable("synoptic_netcdf_wrong_geo_shape")
    if values.size > MAX_NETCDF_NODES:
        raise NetcdfPressureUnavailable("synoptic_netcdf_native_grid_budget")
    missing = source["attrs"].get("_FillValue")
    if isinstance(missing, (int, float)):
        values = np.where(values == missing, float("nan"), values)
    factor = source["attrs"].get("scale_factor", 1.)
    offset = source["attrs"].get("add_offset", 0.)
    if isinstance(factor, (int, float)) and isinstance(offset, (int, float)):
        values = values*factor + offset
    else:
        raise NetcdfPressureUnavailable("synoptic_netcdf_unknown_packing")
    try:
        return regrid_scattered(
            y.ravel(), x.ravel(), values.ravel(), plan,
            run=reference, valid=valid,
            fingerprint=hashlib.sha256(raw).hexdigest()[:24], units=units)
    except GribPressureUnavailable as error:
        raise NetcdfPressureUnavailable(str(error)) from error


def contours_from_netcdf(raw: bytes, plan: dict, *, model: str,
                         provider_id: str, source: str, attribution: str,
                         supplied_run: datetime | None = None) -> dict:
    from .synoptic_gfs import contours
    native = decode_netcdf_pressure(raw, plan, model=model,
                                    supplied_run=supplied_run)
    frame = contours(native)
    frame["model"] = model
    frame["provenance"] = {
        "provider_id": provider_id, "model": model, "source": source,
        "attribution": attribution, "data_origin": "model",
        "measurement_method": "nwp_netcdf_pressure_contours",
        "resampling_method": native["resampling_method"],
    }
    frame["delivery_diagnostics"]["native_nodes"] = native["native_source_nodes"]
    frame["delivery_diagnostics"]["regridded_nodes"] = native["regridded_nodes"]
    return frame
