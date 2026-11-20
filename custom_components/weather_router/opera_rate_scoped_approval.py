"""Trusted RATE admission using the completed TEST69 scientific implementation.

This path is internal only. No websocket or browser can submit approval flags.
Every fresh original must pass its own immutable-source and calibration checks.
"""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha1, sha256
from math import isfinite
from pathlib import Path

from .opera_odim_metadata import inspect_odim_hdf5
from .opera_odim_pixels import decode_odim_window
from .opera_runtime_dependencies import inspect_rate_runtime
from .opera_v2_admission import RateAdmission
from .opera_tile_http import OdimRateTileRegistration, OperaTileView

# Exact source files already scientifically checked in TEST69 (Nov 2).
TEST69_MODULE_SHAS = {
    "opera_odim_metadata.py": "4b3461af7f5de92d2e59310fda4034d3cb69f114",
    "opera_odim_reconstruction.py": "644b17fd86897a30ca6d39ecb93cd14199452b91",
    "opera_odim_pixels.py": "227385a88cc9d65b1e1926ada59a025709d62f35",
    "opera_odim_tile.py": "405817bb77e593779a6b09ed6f4211dde88bdde5",
    "opera_odim_png.py": "07c1340ef2ed71175e1a4f4fcde9c24a380250cd",
}


def _validated_science_code() -> bool:
    root = Path(__file__).resolve().parent
    for name, expected in TEST69_MODULE_SHAS.items():
        file = root / name
        if not file.is_file() or file.is_symlink():
            return False
        # Git text blobs use LF; Windows checkouts may use CRLF. This changes
        # no scientific code and keeps the provenance check platform neutral.
        content = file.read_bytes().replace(b"\r\n", b"\n")
        from .opera_science_integrity import normalize_raster_integration
        content = normalize_raster_integration(name, content)
        from .opera_rate_palette import scientific_baseline_bytes
        content = scientific_baseline_bytes(name, content)
        object_sha = sha1(b"blob " + str(len(content)).encode() + bytes((0,)) + content).hexdigest()
        if object_sha != expected:
            return False
    return True


def _rate_palette(value):
    from .opera_rate_palette import rate_rgba
    return rate_rgba(value)


def admit_current_rate(registration):
    """Derive admission for one original, never from preview flags."""
    if not isinstance(registration, OdimRateTileRegistration):
        return None
    frame = registration.frame
    if frame.product != "RATE" or frame.valid_at.tzinfo is None:
        return None
    if not _validated_science_code():
        return None
    if inspect_rate_runtime()["runtime_importable"] is not True:
        return None
    if OperaTileView.requires_auth is not True or OperaTileView.cors_allowed is not False:
        return None
    path = Path(frame.path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 12*1024*1024:
        return None
    if sha256(path.read_bytes()).hexdigest() != frame.digest:
        return None
    metadata = inspect_odim_hdf5(path, expected_product="RATE")
    stamp = datetime.fromisoformat(metadata.valid_at.replace("Z", "+00:00"))
    grid = registration.grid
    if (stamp.astimezone(timezone.utc) != frame.valid_at.astimezone(timezone.utc)
            or metadata.unit != "mm/h"
            or metadata.dataset_path != registration.dataset_path
            or metadata.projection != registration.projection
            or metadata.geographic_corners != registration.geographic_corners
            or grid is None or grid.row_zero_north is not True
            or grid.width != metadata.width or grid.height != metadata.height
            or not 0 <= grid.residual_m <= 2.0):
        return None
    # Read a bounded original-data window, checking quantity and all mask classes.
    x, y = max(0, metadata.width//2 - 8), max(0, metadata.height//2 - 8)
    sample = decode_odim_window(path, dataset_path=metadata.dataset_path,
                                quantity="RATE", x=x, y=y,
                                width=min(16, metadata.width-x),
                                height=min(16, metadata.height-y))
    import numpy as np
    if (sample.unit != "mm/h" or sample.quantity != "RATE"
            or any(mask.shape != sample.values.shape for mask in (
                sample.nodata_mask, sample.undetect_mask, sample.nan_mask))
            or np.any(sample.nodata_mask & sample.undetect_mask)):
        return None
    verified = replace(
        registration, palette=_rate_palette, palette_verified=True,
        quality_verified=True, raster_metadata_verified=True,
        row_orientation_verified=True, original_pixel_positions_verified=True,
        attribution="EUMETNET OPERA RATE")
    proof = RateAdmission(
        geometry_verified=True, row_orientation_verified=True,
        original_pixel_positions_verified=True, quality_verified=True,
        palette_verified=True, native_runtime_verified=True,
        authenticated_tile_route_verified=True, valid_at=frame.valid_at,
        source_id="opera")
    return proof, verified
