"""Fail-closed projected ODIM grid/window geometry; never a raster/tile approval.

Coordinates are in the source projection's units, not latitude/longitude.
A caller MUST explicitly establish the source row orientation. This module
does not infer orientation from LL/UR corners and does not reproject.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

MAX_GRID_PIXELS = 25_000_000
MAX_WINDOW_PIXELS = 1024 * 1024


class OdimGeometryError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectedGrid:
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    pixel_width: float
    pixel_height: float
    row_zero_north: bool
    raster_approved: bool = False

    def window_bounds(self, *, x: int, y: int, width: int, height: int) -> tuple[float, float, float, float]:
        """Bounds of a bounded pixel window in the unchanged source projection."""
        if any(type(v) is not int for v in (x, y, width, height)):
            raise OdimGeometryError("invalid_window")
        if (x < 0 or y < 0 or width < 1 or height < 1
                or width * height > MAX_WINDOW_PIXELS
                or x + width > self.width or y + height > self.height):
            raise OdimGeometryError("window_out_of_bounds")
        left, bottom, right, top = self.bounds
        west = left + x * self.pixel_width
        east = left + (x + width) * self.pixel_width
        if self.row_zero_north:
            north = top - y * self.pixel_height
            south = top - (y + height) * self.pixel_height
        else:
            south = bottom + y * self.pixel_height
            north = bottom + (y + height) * self.pixel_height
        result = (west, south, east, north)
        if not all(isfinite(v) for v in result) or west >= east or south >= north:
            raise OdimGeometryError("invalid_window_bounds")
        return result


def projected_grid(*, width: int, height: int,
                   projected_extent: tuple[float, float, float, float] | None,
                   row_zero_north: bool | None) -> ProjectedGrid:
    """Construct geometry only with explicit, externally verified row orientation.

    This is not proof of LAEA axis conventions or ODIM corner semantics.
    """
    if type(row_zero_north) is not bool:
        raise OdimGeometryError("row_orientation_unverified")
    if (type(width) is not int or type(height) is not int
            or width < 1 or height < 1 or width * height > MAX_GRID_PIXELS):
        raise OdimGeometryError("invalid_dimensions")
    if projected_extent is None:
        raise OdimGeometryError("projected_extent_missing")
    try:
        bounds = tuple(float(v) for v in projected_extent)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OdimGeometryError("invalid_projected_extent") from exc
    if (len(bounds) != 4 or not all(isfinite(v) for v in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise OdimGeometryError("invalid_projected_extent")
    dx = (bounds[2] - bounds[0]) / width
    dy = (bounds[3] - bounds[1]) / height
    if not all(isfinite(v) and v > 0 for v in (dx, dy)):
        raise OdimGeometryError("invalid_pixel_size")
    return ProjectedGrid(width, height, bounds, dx, dy, row_zero_north)
