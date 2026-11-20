"""Dormant, fail-closed ODIM HDF5 metadata inspection; NO tile admission.

This module is not connected to the provider or Consumer V2. Caller must supply
a locally verified HDF5 file, validated provenance and a worker-thread context.
It does not infer scientific validity from a filename or file-format signature.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from math import isfinite
import re

ODIM_DATE = re.compile(r"[0-9]{8}")
ODIM_TIME = re.compile(r"[0-9]{6}")

MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_PIXELS = 25_000_000
HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
ALLOWED_PRODUCTS = {"RATE": "mm/h", "DBZH": "dBZ", "ACRR": "mm"}


class OdimMetadataError(ValueError):
    pass


@dataclass(frozen=True)
class OdimInspection:
    product: str
    unit: str
    width: int
    height: int
    valid_at: str
    dataset_path: str
    projection: str
    projected_extent: tuple[float, float, float, float] | None = None
    quality_status: str = "UNVERIFIED"
    raster_approved: bool = False
    geographic_corners: dict | None = None
    pixel_scale: tuple[float, float] | None = None


def _value(v):
    if isinstance(v, bytes):
        return v.decode("ascii", "strict")
    return str(v)


def inspect_odim_hdf5(path: Path, *, expected_product: str) -> OdimInspection:
    """Read metadata without loading the raster array, inside a caller-owned worker.

    This is intentionally a preparatory inspector, not a scientific decoder:
    georeferencing, quality, pixel calibration and publication remain blocked.
    """
    if expected_product not in ALLOWED_PRODUCTS:
        raise OdimMetadataError("unsupported_product")
    file = Path(path)
    if file.is_symlink() or not file.is_file():
        raise OdimMetadataError("unsafe_file")
    size = file.stat().st_size
    if not 8 <= size <= MAX_INPUT_BYTES:
        raise OdimMetadataError("file_size_invalid")
    with file.open("rb") as src:
        if src.read(8) != HDF5_SIGNATURE:
            raise OdimMetadataError("not_hdf5")
    try:
        import h5py  # Optional native dependency; never imported on HA automatically.
    except ImportError as exc:
        raise OdimMetadataError("hdf5_dependency_unavailable") from exc

    try:
        with h5py.File(file, "r") as h5:
            if "what" not in h5 or "where" not in h5 or "dataset1" not in h5:
                raise OdimMetadataError("missing_odim_groups")
            what = h5["what"].attrs
            where = h5["where"].attrs
            if _value(what.get("object", "")) not in ("COMP", "IMAGE"):
                raise OdimMetadataError("not_composite")
            date, clock = _value(what.get("date", "")), _value(what.get("time", ""))
            if not ODIM_DATE.fullmatch(date) or not ODIM_TIME.fullmatch(clock):
                raise OdimMetadataError("invalid_odim_utc")
            try:
                valid_at = datetime.strptime(date + clock, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise OdimMetadataError("invalid_odim_utc") from exc
            try:
                width = int(where.get("xsize", 0))
                height = int(where.get("ysize", 0))
            except (TypeError, ValueError, OverflowError) as exc:
                raise OdimMetadataError("invalid_grid_dimensions") from exc
            if not (0 < width <= MAX_PIXELS and 0 < height <= MAX_PIXELS
                    and width * height <= MAX_PIXELS):
                raise OdimMetadataError("oversized_grid")
            projection = _value(where.get("projdef", ""))
            if not projection or len(projection) > 4096 or chr(0) in projection:
                raise OdimMetadataError("missing_projection")
            # ODIM projected corner coordinates are optional in source files.
            # A missing extent MUST NOT be mistaken for an approved georeference.
            corner_names = ("LL_x", "LL_y", "UR_x", "UR_y")
            present = [name in where for name in corner_names]
            extent = None
            if any(present):
                if not all(present):
                    raise OdimMetadataError("incomplete_projected_extent")
                try:
                    corners = tuple(float(where[name]) for name in corner_names)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise OdimMetadataError("invalid_projected_extent") from exc
                if (not all(isfinite(value) for value in corners)
                        or corners[0] >= corners[2] or corners[1] >= corners[3]):
                    raise OdimMetadataError("invalid_projected_extent")
                extent = corners
            # Use only coordinates actually present in the ODIM original.
            corner_labels = ("LL", "LR", "UL", "UR")
            coordinate_keys = tuple(f"{label}_{axis}" for label in corner_labels for axis in ("lat", "lon"))
            geographic = None
            flags = [key in where for key in coordinate_keys]
            if any(flags):
                if not all(flags):
                    raise OdimMetadataError("incomplete_geographic_corners")
                try:
                    geographic = {label: (float(where[f"{label}_lat"]),
                                          float(where[f"{label}_lon"]))
                                  for label in corner_labels}
                except (TypeError, ValueError, OverflowError) as exc:
                    raise OdimMetadataError("invalid_geographic_corners") from exc
                if not all(isfinite(lat) and isfinite(lon) and -90 <= lat <= 90
                           and -180 <= lon <= 180
                           for lat, lon in geographic.values()):
                    raise OdimMetadataError("invalid_geographic_corners")
            scale = None
            if "xscale" in where and "yscale" in where:
                try:
                    xscale, yscale = float(where["xscale"]), float(where["yscale"])
                    if isfinite(xscale) and isfinite(yscale) and xscale > 0 and yscale > 0:
                        scale = (xscale, yscale)
                except (TypeError, ValueError, OverflowError):
                    pass
            matches = []
            for key, value in h5["dataset1"].items():
                if not key.startswith("data") or not isinstance(value, h5py.Group) or "what" not in value or "data" not in value:
                    continue
                attrs = value["what"].attrs
                if _value(attrs.get("quantity", "")) != expected_product:
                    continue
                raster = value["data"]
                if not isinstance(raster, h5py.Dataset):
                    raise OdimMetadataError("invalid_data_node")
                if raster.ndim != 2 or raster.shape != (height, width):
                    raise OdimMetadataError("grid_shape_mismatch")
                for field in ("gain", "offset", "nodata", "undetect"):
                    v = attrs.get(field)
                    try:
                        good = v is not None and isfinite(float(v))
                    except (TypeError, ValueError, OverflowError):
                        good = False
                    if not good:
                        raise OdimMetadataError("invalid_calibration")
                if float(attrs["gain"]) <= 0 or float(attrs["nodata"]) == float(attrs["undetect"]):
                    raise OdimMetadataError("invalid_calibration")
                matches.append(value.name + "/data")
            if len(matches) != 1:
                raise OdimMetadataError("quantity_missing_or_ambiguous")
            return OdimInspection(
                expected_product, ALLOWED_PRODUCTS[expected_product], width, height,
                valid_at.isoformat().replace("+00:00", "Z"),
                matches[0], projection, extent,
                geographic_corners=geographic,
                pixel_scale=scale,
            )
    except OSError as exc:
        raise OdimMetadataError("hdf5_read_error") from exc
