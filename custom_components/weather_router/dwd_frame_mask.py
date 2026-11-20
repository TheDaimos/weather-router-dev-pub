"""Optional, pre-staged DWD WCS NoData evidence for one exact WMS frame."""
from __future__ import annotations

import base64
from datetime import datetime
from functools import lru_cache
import json
from math import isfinite
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

DWD_RADAR = "dwd/radar_precipitation"
SCHEMA = "dwd_wcs_nodata_v1"
MAX_CELLS = 2_000_000
MAX_FILE_BYTES = 350_000


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() is None or stamp.microsecond:
        raise ValueError("Whole-second timezone-aware radar time required")
    return int(stamp.timestamp())


def validate_mask(mask):
    """Only set bits denote measured NoData. Unset and uncovered stay protected."""
    if not isinstance(mask, dict) or set(mask) != {
        "kind", "valid_at", "reference_at", "width", "height", "bounds", "bits"
    } or mask["kind"] != SCHEMA:
        raise ValueError("Invalid DWD mask type")
    if _stamp(mask["reference_at"]) != _stamp(mask["valid_at"]):
        raise ValueError("Only exact analysis runs are supported")
    width, height = mask["width"], mask["height"]
    if (type(width) is not int or type(height) is not int
            or not 1 <= width <= 4096 or not 1 <= height <= 4096
            or width * height > MAX_CELLS):
        raise ValueError("Invalid DWD grid size")
    bounds = mask["bounds"]
    if (not isinstance(bounds, list) or len(bounds) != 4
            or not all(type(v) in (int, float) and isfinite(v) for v in bounds)):
        raise ValueError("Invalid DWD grid bounds")
    west, south, east, north = bounds
    if not -180 <= west < east <= 180 or not -85.052 <= south < north <= 85.052:
        raise ValueError("Invalid DWD grid coordinates")
    bits = base64.b64decode(mask["bits"], validate=True)
    if len(bits) != (width * height + 7) // 8:
        raise ValueError("Invalid DWD mask length")
    return mask


@lru_cache(maxsize=4)
def _read_mask(path, mtime, length):
    if length > MAX_FILE_BYTES:
        raise ValueError("DWD mask exceeds byte budget")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) != length:
        raise ValueError("DWD mask changed during read")
    return validate_mask(json.loads(data))


def cached_mask(directory, layer):
    """Disk and memory only. A missing or inconsistent file grants nothing."""
    if directory is None:
        return None, "not_configured"
    try:
        stamp = _stamp(layer["times"]["valid_at"])
        url = urlsplit(layer["tile_url"])
        query = parse_qs(url.query)
        if (url.scheme != "https" or url.hostname not in {"maps.dwd.de", "brz-maps.dwd.de"}
                or url.path != "/geoserver/dwd/wms"
                or query.get("layers") != ["Niederschlagsradar"]
                or "dim_reference_time" in {key.lower() for key in query}
                or _stamp(query["time"][0]) != stamp):
            return None, "unsupported_wms_frame"
        path = Path(directory) / f"{stamp}.json"
        stat = path.stat()
        mask = _read_mask(path, stat.st_mtime_ns, stat.st_size)
        if _stamp(mask["valid_at"]) != stamp:
            return None, "frame_mismatch"
        return mask, "verified"
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None, "invalid"


def pin_wms_run(url, reference_at):
    # Add the OGC custom dimension without rewriting the live BBOX placeholder.
    return url + "&dim_reference_time=" + quote(reference_at, safe="")
