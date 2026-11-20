"""Explicit offline-only ODIM HDF5 window decoding; never tile approval."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from math import isfinite
import re

DATASET_PATH = re.compile(r"/dataset1/data[1-9][0-9]*/data")

MAX_WINDOW_PIXELS = 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024

class OdimWindowError(ValueError):
    pass

@dataclass(frozen=True)
class OdimWindow:
    values: object
    nodata_mask: object
    undetect_mask: object
    quantity: str
    unit: str
    raster_approved: bool = False
    nan_mask: object = None

def decode_odim_window(path: Path, *, dataset_path: str, quantity: str,
                       x: int, y: int, width: int, height: int) -> OdimWindow:
    """Read a bounded subset. NoData and Undetect remain distinct invalid masks.

    Caller must separately validate provenance, timestamp, coverage, and geometry
    and perform this operation in a worker. This is NOT an approved renderer.
    """
    if quantity not in ("RATE", "DBZH", "ACRR"):
        raise OdimWindowError("unknown_quantity")
    if (not isinstance(dataset_path, str)
            or not DATASET_PATH.fullmatch(dataset_path)):
        raise OdimWindowError("invalid_dataset_path")
    if (any(type(v) is not int for v in (x, y, width, height))
            or min(x, y) < 0 or min(width, height) < 1
            or width * height > MAX_WINDOW_PIXELS):
        raise OdimWindowError("invalid_window")
    path = Path(path)
    if (path.is_symlink() or not path.is_file()
            or not 8 <= path.stat().st_size <= MAX_FILE_BYTES):
        raise OdimWindowError("unsafe_file")
    with path.open("rb") as inp:
        if inp.read(8) != b"\x89HDF\r\n\x1a\n":
            raise OdimWindowError("not_hdf5")
    try:
        import h5py
        import numpy as np
    except ImportError as exc:
        raise OdimWindowError("decoder_dependency_unavailable") from exc
    try:
        with h5py.File(path, "r") as h5:
            if dataset_path not in h5:
                raise OdimWindowError("missing_dataset")
            ds = h5[dataset_path]
            if (not isinstance(ds, h5py.Dataset) or ds.ndim != 2
                    or x + width > ds.shape[1] or y + height > ds.shape[0]):
                raise OdimWindowError("window_out_of_bounds")
            parent = ds.parent
            if "what" not in parent:
                raise OdimWindowError("missing_calibration")
            attrs = parent["what"].attrs
            quantity_attr = attrs.get("quantity", "")
            # ODIM fixed-width HDF5 strings may carry ASCII NUL/space padding.
            # Do not reinterpret or alias a different quantity.
            if isinstance(quantity_attr, (bytes, np.bytes_)):
                try:
                    quantity_attr = bytes(quantity_attr).decode("ascii", "strict")
                except UnicodeDecodeError as exc:
                    raise OdimWindowError("quantity_mismatch") from exc
            if not isinstance(quantity_attr, str):
                raise OdimWindowError("quantity_mismatch")
            quantity_attr = quantity_attr.rstrip("\x00 ")
            if quantity_attr != quantity:
                raise OdimWindowError("quantity_mismatch")
            try:
                gain, offset, nodata, undetect = (
                    float(attrs[key]) for key in ("gain", "offset", "nodata", "undetect"))
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                raise OdimWindowError("invalid_calibration") from exc
            if (not all(isfinite(v) for v in (gain, offset, nodata, undetect))
                    or gain <= 0 or nodata == undetect):
                raise OdimWindowError("invalid_calibration")
            raw = ds[y:y+height, x:x+width]
            if raw.dtype.kind not in "uif" or raw.size > MAX_WINDOW_PIXELS:
                raise OdimWindowError("invalid_raster_dtype")
            # SCI-03: never classify non-finite originals as ODIM nodata.
            # Each category remains individually inspectable; none can render as rain.
            nan = ~np.isfinite(raw)
            no = (raw == nodata) & ~nan
            un = (raw == undetect) & ~nan & ~no
            # Keep source float64 precision until calibrated; do not silently round OPERA originals.
            values = raw.astype(np.float64) * gain + offset
            values[no | un | nan] = np.nan
            return OdimWindow(values, no, un, quantity,
                              {"RATE": "mm/h", "DBZH": "dBZ", "ACRR": "mm"}[quantity], nan_mask=nan)
    except OSError as exc:
        raise OdimWindowError("hdf5_read_failure") from exc
