"""Passive reconstruction of LAEA raster bounds from the four original ODIM corners.

Corner values are (latitude, longitude), and refer to OUTER pixel boundaries.
No scientific raster admission, network access or automatic row orientation.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite

class OperaReconstructionError(ValueError):
    pass

@dataclass(frozen=True)
class ReconstructedGrid:
    bounds: tuple[float, float, float, float]
    pixel_size: tuple[float, float]
    residual_m: float
    width: int
    height: int
    row_zero_north: bool
    raster_approved: bool = False

    def center(self, column: int, row: int) -> tuple[float, float]:
        if (type(column) is not int or type(row) is not int
                or not 0 <= column < self.width or not 0 <= row < self.height):
            raise OperaReconstructionError("invalid_pixel_index")
        left, bottom, _, top = self.bounds
        dx, dy = self.pixel_size
        return (left + (column + 0.5) * dx,
                top - (row + 0.5) * dy if self.row_zero_north
                else bottom + (row + 0.5) * dy)


def reconstruct_laea(*, projection: str, corners: dict, width: int,
                     height: int, xscale: float, yscale: float,
                     row_zero_north: bool | None,
                     tolerance_m: float = 2.0) -> ReconstructedGrid:
    """Validate every original geographic corner and the nominal pixel sizes."""
    if type(row_zero_north) is not bool:
        raise OperaReconstructionError("row_orientation_unverified")
    if (type(width) is not int or type(height) is not int
            or width < 1 or height < 1 or width * height > 25_000_000):
        raise OperaReconstructionError("invalid_dimensions")
    if (not isinstance(projection, str) or len(projection) > 4096
            or "+proj=laea" not in projection.lower().split()):
        raise OperaReconstructionError("invalid_laea_projection")
    if not isinstance(corners, dict) or set(corners) != {"LL", "LR", "UL", "UR"}:
        raise OperaReconstructionError("missing_corners")
    try:
        dx, dy, tolerance = float(xscale), float(yscale), float(tolerance_m)
    except (TypeError, ValueError, OverflowError) as exc:
        raise OperaReconstructionError("invalid_scale") from exc
    if not all(isfinite(v) and v > 0 for v in (dx, dy, tolerance)):
        raise OperaReconstructionError("invalid_scale")
    try:
        from pyproj import CRS, Transformer
    except ImportError as exc:
        raise OperaReconstructionError("pyproj_unavailable") from exc
    try:
        source = CRS.from_user_input(projection)
        if not source.is_projected:
            raise ValueError("projection_not_projected")
        transformer = Transformer.from_crs(CRS.from_epsg(4326), source, always_xy=True)
        xy = {}
        for name in ("LL", "LR", "UL", "UR"):
            latitude, longitude = map(float, corners[name])
            if (not -90 <= latitude <= 90 or not -180 <= longitude <= 180
                    or not isfinite(latitude) or not isfinite(longitude)):
                raise ValueError("geographical_corner_invalid")
            xy[name] = transformer.transform(longitude, latitude)
            if not all(isfinite(v) for v in xy[name]):
                raise ValueError("projected_corner_invalid")
    except Exception as exc:
        raise OperaReconstructionError("invalid_corner_projection") from exc
    left = (xy["LL"][0] + xy["UL"][0]) / 2
    right = (xy["LR"][0] + xy["UR"][0]) / 2
    bottom = (xy["LL"][1] + xy["LR"][1]) / 2
    top = (xy["UL"][1] + xy["UR"][1]) / 2
    target = {"LL": (left, bottom), "LR": (right, bottom),
              "UL": (left, top), "UR": (right, top)}
    residual = max(abs(xy[k][i] - target[k][i]) for k in target for i in (0, 1))
    residual = max(residual, abs(right-left-width*dx), abs(top-bottom-height*dy))
    if not left < right or not bottom < top or residual > tolerance:
        raise OperaReconstructionError("corner_grid_mismatch")
    return ReconstructedGrid((left, bottom, right, top), (dx, dy), residual,
                             width, height, row_zero_north)
