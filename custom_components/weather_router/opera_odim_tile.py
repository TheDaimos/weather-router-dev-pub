"""Offline bounded nearest-neighbor Web Mercator tile from an explicitly verified RATE grid.

This is NOT wired to the Consumer API: publication requires scientific admission,
authorized native dependencies, tested imagery and a verified north-up contract.
"""
from __future__ import annotations
from math import pi, atan, sinh
from pathlib import Path

class OperaTileError(ValueError):
    pass

def decode_rate_tile(path: Path, *, grid, projection: str, dataset_path: str,
                     x: int, y: int, z: int, orientation_verified: bool,
                     tile_size: int = 256):
    """Return (uint8 RGBA array, coverage boolean); never silently blend products.

    Only the minimal rectangular source window enclosing inside-grid target pixels
    is read. Colour scale is a diagnostic ramp, not a released GR legend.
    """
    if orientation_verified is not True or grid.row_zero_north is not True:
        raise OperaTileError("orientation_not_approved")
    if (any(type(v) is not int for v in (x, y, z, tile_size))
            or z < 0 or z > 20 or tile_size != 256 or
            not 0 <= x < (1 << z) or not 0 <= y < (1 << z)):
        raise OperaTileError("invalid_tile_coordinates")
    try:
        import numpy as np
        from pyproj import Transformer, CRS
    except ImportError as exc:
        raise OperaTileError("native_dependency_unavailable") from exc
    if not isinstance(projection, str) or "+proj=laea" not in projection.lower().split():
        raise OperaTileError("invalid_projection")
    try:
        sx, sy, finite_xy, col, row = rate_tile_coordinates(
            grid, projection, x=x, y=y, z=z, tile_size=tile_size)
        inside = (finite_xy & (col >= 0)
                  & (row >= 0) & (col < grid.width) & (row < grid.height))
        rgba = np.zeros((tile_size, tile_size, 4), dtype=np.uint8)
        if not np.any(inside):
            return rgba, False
        cols = col[inside]
        rows = row[inside]
        x0, x1 = int(cols.min()), int(cols.max()) + 1
        y0, y1 = int(rows.min()), int(rows.max()) + 1
        # Preserve the exact approved sample positions and decode/calibration;
        # split only the enclosing I/O rectangle into bounded source windows.
        valid = np.zeros((tile_size, tile_size), dtype=bool)
        values = np.zeros((tile_size, tile_size), dtype=np.float64)
        from .opera_odim_pixels import decode_odim_window, MAX_WINDOW_PIXELS
        rows_per_window = max(1, MAX_WINDOW_PIXELS // (x1-x0))
        for start in range(y0, y1, rows_per_window):
            end = min(y1, start+rows_per_window)
            selected = inside & (row >= start) & (row < end)
            if not np.any(selected):
                continue
            window = decode_odim_window(path, dataset_path=dataset_path,
                quantity="RATE", x=x0, y=start, width=x1-x0, height=end-start)
            rr, cc = row[selected]-start, col[selected]-x0
            valid[selected] = (~window.nodata_mask[rr, cc]
                & ~window.undetect_mask[rr, cc] & ~window.nan_mask[rr, cc])
            values[selected] = window.values[rr, cc]
        from .opera_rate_palette import colorize_rate
        valid &= np.isfinite(values) & (values > 0)
        rgba = colorize_rate(values, valid)
        return rgba, bool(np.any(valid))
    except OperaTileError:
        raise
    except Exception as exc:
        raise OperaTileError("tile_decode_failed") from exc


def rate_projection(projection):
    """Shared existing LAEA transformer; no independent mask georeference."""
    from pyproj import Transformer, CRS
    crs = CRS.from_user_input(projection)
    return Transformer.from_crs(CRS.from_epsg(4326), crs, always_xy=True)


def rate_tile_coordinates(grid, projection, *, x, y, z, tile_size=256, edges=False):
    """Original north-first mapping; edges is only for conservative mask cells."""
    import numpy as np
    from math import pi
    transformer = rate_projection(projection)
    axis = (np.arange(tile_size + (1 if edges else 0), dtype=np.float64)
            + (0.0 if edges else 0.5)) / tile_size
    normalized_lon = (x + axis) / (1 << z)
    normalized_y = (y + axis) / (1 << z)
    lon = normalized_lon * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(pi * (1.0 - 2.0 * normalized_y))))
    longitude, latitude = np.meshgrid(lon, lat)
    sx, sy = transformer.transform(longitude, latitude)
    left, bottom, _, top = grid.bounds
    dx, dy = grid.pixel_size
    finite_xy = np.isfinite(sx) & np.isfinite(sy)
    col = np.floor(np.where(finite_xy, (sx - left) / dx, -1)).astype(np.int64)
    row = np.floor(np.where(finite_xy, (top - sy) / dy, -1)).astype(np.int64)
    return sx, sy, finite_xy, col, row
