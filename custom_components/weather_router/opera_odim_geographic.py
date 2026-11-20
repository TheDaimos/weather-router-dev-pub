"""Offline-only bounded OPERA projected-window to geographical bounds conversion.

No consumer endpoint uses this module and no scientific raster approval is
implied. Source projection and row orientation must be independently verified.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite

MAX_SAMPLES_PER_SIDE = 17

class OperaProjectionError(ValueError):
    pass

@dataclass(frozen=True)
class GeographicFootprint:
    west: float
    south: float
    east: float
    north: float
    sample_count: int
    raster_approved: bool = False


def geographic_window_footprint(grid, *, x: int, y: int, width: int,
                                height: int, source_crs: str,
                                orientation_verified: bool,
                                samples_per_side: int = 9) -> GeographicFootprint:
    """Transform boundary samples, not merely projected BBOX corners.

    A bounding box is only a conservative footprint and must not be used as
    a full per-pixel reprojection or a scientifically approved tile.
    """
    if orientation_verified is not True:
        raise OperaProjectionError("row_orientation_unverified")
    if type(samples_per_side) is not int or not 2 <= samples_per_side <= MAX_SAMPLES_PER_SIDE:
        raise OperaProjectionError("invalid_sampling")
    if not isinstance(source_crs, str) or not 1 <= len(source_crs) <= 4096:
        raise OperaProjectionError("invalid_source_projection")
    if "+proj=laea" not in source_crs.lower().split():
        raise OperaProjectionError("unverified_laea_projection")
    bounds = grid.window_bounds(x=x, y=y, width=width, height=height)
    try:
        from pyproj import CRS, Transformer
    except ImportError as exc:
        raise OperaProjectionError("pyproj_unavailable") from exc
    try:
        src = CRS.from_user_input(source_crs)
        if src.is_geographic or not src.is_projected:
            raise OperaProjectionError("source_not_projected")
        transformer = Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
        left, bottom, right, top = bounds
        steps = (samples_per_side - 1)
        samples = []
        for k in range(samples_per_side):
            fraction = k / steps
            xx = left + fraction * (right - left)
            yy = bottom + fraction * (top - bottom)
            samples.extend(((xx, bottom), (xx, top),
                            (left, yy), (right, yy)))
        lon, lat = transformer.transform([a for a, b in samples], [b for a, b in samples])
    except OperaProjectionError:
        raise
    except Exception as exc:
        raise OperaProjectionError("coordinate_transform_failure") from exc
    if (not all(isfinite(v) and -90 <= v <= 90 for v in lat)
            or not all(isfinite(v) and -180 <= v <= 180 for v in lon)):
        raise OperaProjectionError("invalid_transformed_bounds")
    # Reject anti-meridian crosses until a wrap-aware tile contract exists.
    if max(lon) - min(lon) >= 180:
        raise OperaProjectionError("antimeridian_not_supported")
    if min(lon) >= max(lon) or min(lat) >= max(lat):
        raise OperaProjectionError("degenerate_footprint")
    return GeographicFootprint(min(lon), min(lat), max(lon), max(lat), len(samples))
