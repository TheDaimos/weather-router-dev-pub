"""Isolated historical OPERA ODIM metadata probe; NEVER register a frame.

An exclusive lock prevents concurrent maintenance from deleting active files.
Only old owned regular files are reaped; running jobs remain untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import os
import tempfile
import time
import fcntl
from math import isfinite

PREFIX = "wr-opera-history-"
STALE_SECONDS = 3600
MAX_BYTES = 12 * 1024 * 1024
ROOT = Path(tempfile.gettempdir()) / "weather-router-opera-history"


def _workspace():
    if ROOT.is_symlink():
        raise ValueError("unsafe_history_directory")
    ROOT.mkdir(mode=0o700, exist_ok=True)
    if ROOT.is_symlink() or not ROOT.is_dir() or ROOT.stat().st_mode & 0o077:
        raise ValueError("unsafe_history_directory")
    return ROOT


def cleanup_orphans():
    """Reap only owned, old files; never delete directories, links, or active jobs."""
    root = _workspace()
    removed = 0
    now = time.time()
    for item in root.iterdir():
        if not item.name.startswith(PREFIX) or not item.name.endswith(".h5"):
            continue
        if item.is_symlink() or not item.is_file():
            continue
        if now - item.stat().st_mtime < STALE_SECONDS:
            continue
        lock = item.with_suffix(".lock")
        # No lock file means no authenticated ownership evidence: fail closed.
        if lock.is_symlink() or not lock.is_file():
            continue
        with lock.open("rb") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            item.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)
            removed += 1
    return removed


def inspect_historical_bytes(data: bytes, *, expected_filename_utc: str):
    """Executor-only, no cache/registry writes. Always delete before returning."""
    if not 8 <= len(data) <= MAX_BYTES or data[:8] != b"\x89HDF\r\n\x1a\n":
        raise ValueError("invalid_historical_hdf5")
    root = _workspace()
    fd, filename = tempfile.mkstemp(dir=root, prefix=PREFIX, suffix=".h5")
    target = Path(filename)
    lock = target.with_suffix(".lock")
    digest = sha256(data).hexdigest()
    try:
        fd_lock = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        with os.fdopen(fd_lock, "rb") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            with os.fdopen(fd, "wb") as out:
                fd = -1
                out.write(data)
            from .opera_odim_metadata import inspect_odim_hdf5
            inspected = inspect_odim_hdf5(target, expected_product="RATE")
            # Examine bounded raw values at five identifiable pixel locations.
            # No orientation inference is permitted from raw values alone.
            import h5py
            with h5py.File(target, "r") as source:
                dataset = source[inspected.dataset_path]
                # Read calibration from the same original ODIM data group.
                # Sentinel values must never be reported as precipitation.
                attrs = dataset.parent["what"].attrs
                calibration = {key: float(attrs[key]) for key in
                               ("gain", "offset", "nodata", "undetect")}
                if not all(isfinite(value) for value in calibration.values()):
                    raise ValueError("invalid_calibration")
                if calibration["gain"] <= 0 or calibration["nodata"] == calibration["undetect"]:
                    raise ValueError("invalid_calibration")
                positions = ((0, 0), (0, inspected.width - 1),
                             (inspected.height // 2, inspected.width // 2),
                             (inspected.height - 1, 0),
                             (inspected.height - 1, inspected.width - 1))
                sample = []
                for row, column in positions:
                    raw_value = dataset[row, column].item()
                    numeric = float(raw_value)
                    classification = ("NONFINITE" if not isfinite(numeric) else
                                      "NODATA" if numeric == calibration["nodata"] else
                                      "UNDETECT" if numeric == calibration["undetect"] else
                                      "MEASUREMENT")
                    sample.append({"row": row, "column": column,
                                   "raw": numeric if isfinite(numeric) else None,
                                   "classification": classification,
                                   "rate_mm_h": round(numeric * calibration["gain"] +
                                                      calibration["offset"], 8)
                                   if classification == "MEASUREMENT" else None})
            # Georeferencing remains a hypothesis until an independent
            # original-pixel orientation reference has been validated.
            geometry = {"projected_extent_present": inspected.projected_extent is not None,
                        "row_zero_north": "UNVERIFIED",
                        "pixel_positions_verified": False}
            # Calculate both pixel-center hypotheses from *original* source
            # corners and scales; do not infer orientation or approve pixels.
            if inspected.geographic_corners and inspected.pixel_scale:
                from .opera_odim_reconstruction import reconstruct_laea, OperaReconstructionError
                try:
                    grid = reconstruct_laea(
                        projection=inspected.projection,
                        corners=inspected.geographic_corners,
                        width=inspected.width, height=inspected.height,
                        xscale=inspected.pixel_scale[0],
                        yscale=inspected.pixel_scale[1],
                        row_zero_north=True)
                    from pyproj import CRS, Transformer
                    transformer = Transformer.from_crs(
                        CRS.from_user_input(inspected.projection),
                        CRS.from_epsg(4326), always_xy=True)
                    sample_geographic = []
                    for item in sample:
                        east, north = grid.center(item["column"], item["row"])
                        lon_n, lat_n = transformer.transform(east, north)
                        left, bottom, right, top = grid.bounds
                        dy = grid.pixel_size[1]
                        south_north = bottom + (item["row"] + 0.5) * dy
                        lon_s, lat_s = transformer.transform(east, south_north)
                        # Flat scalar fields survive the bounded Export2Git
                        # redaction depth, unlike nested lat/lon arrays.
                        sample_geographic.append({
                            "row": item["row"], "column": item["column"],
                            "north_first_lat": round(lat_n, 8),
                            "north_first_lon": round(lon_n, 8),
                            "south_first_lat": round(lat_s, 8),
                            "south_first_lon": round(lon_s, 8)})
                    geometry.update({
                        "source_geographic_corners_present": True,
                        "source_pixel_scales_present": True,
                        "grid_residual_m": grid.residual_m,
                        "pixel_centers_hypotheses": sample_geographic,
                        "independent_orientation_reference": "NOT_PROVIDED",
                        "orientation_verification": "UNVERIFIED",
                        "orientation_evidence": {
                            "status": "UNVERIFIED",
                            "reference_source": "NONE",
                            "reference_valid_at_utc": None,
                            "original_valid_at_utc": inspected.valid_at,
                            "north_first_residual_m": None,
                            "south_first_residual_m": None,
                            "threshold_m": None,
                            "reason": "independent_georeferenced_pixel_reference_missing",
                        },
                        "row_zero_north": "UNVERIFIED",
                        "pixel_positions_verified": False})
                except (OperaReconstructionError, ValueError, OverflowError):
                    geometry["georeferencing_status"] = "SOURCE_GEOMETRY_REJECTED"
            else:
                geometry.update({
                    "georeferencing_status": "SOURCE_CORNERS_OR_SCALE_MISSING",
                    "source_geographic_corners_present": bool(inspected.geographic_corners),
                    "source_pixel_scales_present": bool(inspected.pixel_scale)})
            nominal = datetime.fromisoformat(expected_filename_utc.replace("Z","+00:00"))
            actual = datetime.fromisoformat(inspected.valid_at.replace("Z","+00:00"))
            return {
                "status": "historical_metadata_only",
                "sha256": digest, "bytes": len(data),
                "odim_utc": inspected.valid_at,
                "filename_utc_matches_odim": actual == nominal,
                "width": inspected.width, "height": inspected.height,
                "product": inspected.product, "unit": inspected.unit,
                "projection_present": bool(inspected.projection),
                "pixel_samples": sample, "geometry": geometry,
                "odim_calibration": calibration,
                "pixel_quality_diagnostic": {
                    "sample_count": len(sample),
                    "measurement_count": sum(item["classification"] == "MEASUREMENT" for item in sample),
                    "nodata_count": sum(item["classification"] == "NODATA" for item in sample),
                    "undetect_count": sum(item["classification"] == "UNDETECT" for item in sample),
                    "nonfinite_count": sum(item["classification"] == "NONFINITE" for item in sample),
                    "full_raster_quality_verified": False,
                    "status": "SAMPLES_ONLY",
                },
                "orientation_reference_status": "INDEPENDENT_REFERENCE_MISSING",
                "scientific_approval": False,
                "consumer_v2_status": "BLOCKED",
                "frame_registered": False,
                "cleanup": "deleted",
            }
    finally:
        if fd >= 0:
            os.close(fd)
        target.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
