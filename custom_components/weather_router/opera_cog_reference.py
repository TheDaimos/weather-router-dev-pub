"""Strict external GeoTIFF controls for OPERA image orientation; no approval.

Only trusted executor-side callers supply separately sourced, provenance-checked
CoG originals. This does not register or render a tile, nor does it replace
the scientific and operational admission gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from pathlib import Path

from .opera_orientation_evidence import ControlPoint, verify_orientation
from .opera_odim_metadata import inspect_odim_hdf5


class ExternalReferenceError(ValueError):
    pass


@dataclass(frozen=True)
class ReferenceComparison:
    hdf5_sha256: str
    cog_sha256: str
    valid_at: str
    sample_count: int
    row_zero_north: bool
    opposite_matches: int
    source: str
    scientifically_approved: bool = False


def _sha(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def compare_official_cog(*, hdf5_path: Path, cog_path: Path,
                         hdf5_sha256: str, cog_sha256: str,
                         independent_source: str, expected_valid_at: str,
                         grid, tolerance_raw: float = 0.5) -> ReferenceComparison:
    """Compare 9 spatially distributed native pixels to independent GeoTIFF.

    The caller must verify the CoG's official provenance and same RATE UTC time
    independently. Independent calibration and georeferencing are required.
    Never call from the HA event loop.
    """
    if independent_source != "EUMETNET_OPERA_OFFICIAL_COG":
        raise ExternalReferenceError("untrusted_reference_origin")
    if not isinstance(expected_valid_at, str) or not expected_valid_at.endswith("Z"):
        raise ExternalReferenceError("unverified_reference_time")
    for path, digest in ((hdf5_path, hdf5_sha256), (cog_path, cog_sha256)):
        path = Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 512 * 1024 * 1024:
            raise ExternalReferenceError("unsafe_reference_file")
        if not isinstance(digest, str) or len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest):
            raise ExternalReferenceError("invalid_reference_digest")
        if _sha(path) != digest:
            raise ExternalReferenceError("reference_digest_mismatch")
    meta = inspect_odim_hdf5(Path(hdf5_path), expected_product="RATE")
    if meta.valid_at != expected_valid_at:
        raise ExternalReferenceError("reference_time_mismatch")
    if (getattr(grid, "width", None) != meta.width or
            getattr(grid, "height", None) != meta.height or
            getattr(grid, "row_zero_north", None) is not True or
            getattr(grid, "raster_approved", True) is not False):
        raise ExternalReferenceError("unverified_reference_grid")
    if meta.width < 10 or meta.height < 10:
        raise ExternalReferenceError("insufficient_spatial_coverage")
    try:
        import h5py
        import rasterio
        from pyproj import Transformer
        from .opera_orientation_evidence import OrientationEvidenceError
        with h5py.File(hdf5_path, "r") as h:
            ds = h[meta.dataset_path]
            parts = meta.dataset_path.strip("/").split("/")
            what_path = "/".join(parts[:-1] + ["what"])
            attrs = h[what_path].attrs
            gain, offset = float(attrs["gain"]), float(attrs["offset"])
            nodata, undetect = float(attrs["nodata"]), float(attrs["undetect"])
            if not all(isfinite(n) for n in (gain, offset, nodata, undetect)) or gain <= 0:
                raise ExternalReferenceError("invalid_odim_calibration")
        with rasterio.open(cog_path) as ref:
            if ref.count not in (1, 2) or ref.crs is None or not ref.transform.is_rectilinear:
                raise ExternalReferenceError("invalid_reference_geography")
            transformer = Transformer.from_crs(meta.projection, ref.crs, always_xy=True)
            # 9 spatially independent, well-separated sites, never extracted
            # or selected based on values in the HDF5 being checked.
            cols = [meta.width // 5, meta.width // 2, meta.width * 4 // 5]
            rows = [meta.height // 5, meta.height // 2, meta.height * 4 // 5]
            samples = []
            for y in rows:
                for x in cols:
                    projected_x, projected_y = grid.center(x, y)
                    rx, ry = transformer.transform(projected_x, projected_y)
                    val = next(ref.sample([(rx, ry)], indexes=1, masked=True))[0]
                    if bool(getattr(val, "mask", False)) or not isfinite(float(val)):
                        continue
                    raw = (float(val) - offset) / gain
                    # Select using only independent CoG values, never HDF5.
                    if not isfinite(raw) or abs(raw - nodata) <= tolerance_raw or abs(raw - undetect) <= tolerance_raw:
                        continue
                    samples.append(ControlPoint(x, y, raw))
            if (len(samples) < 3 or len({p.column for p in samples}) < 2
                    or len({p.north_up_row for p in samples}) < 2):
                raise ExternalReferenceError("insufficient_independent_controls")
        finding = verify_orientation(
            hdf5_path, dataset_path=meta.dataset_path, width=meta.width,
            height=meta.height, controls=tuple(samples), tolerance=tolerance_raw)
        if not finding.verified or finding.opposite_matches == len(samples):
            raise ExternalReferenceError("orientation_not_discriminated")
    except ExternalReferenceError:
        raise
    except (ImportError, ValueError, OSError, KeyError, TypeError) as exc:
        raise ExternalReferenceError("reference_comparison_failed") from exc
    return ReferenceComparison(
        hdf5_sha256, cog_sha256, meta.valid_at, len(samples),
        finding.row_zero_north, finding.opposite_matches, independent_source)
