"""Evidence-based ODIM raster row orientation from independently labelled pixels.

Geographic corners determine projected cell locations, NOT the storage order.
A positive decision needs authenticated external observations of native pixel
values at known projected centres. No guess from array conventions or a bbox.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite


class OrientationEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class ControlPoint:
    column: int
    north_up_row: int
    expected_raw_value: float


@dataclass(frozen=True)
class OrientationFinding:
    row_zero_north: bool
    matching_controls: int
    opposite_matches: int
    verified: bool = False


def verify_orientation(path, *, dataset_path: str, width: int, height: int,
                       controls: tuple[ControlPoint, ...],
                       tolerance: float = 1e-8) -> OrientationFinding:
    """Test both storage orientations; reject ambiguity and undocumented points.

    Controls must come from independently verified geographical pixel samples.
    Caller is responsible for their scientific provenance, never self-label
    controls using pixels read from this same file.
    """
    if not isinstance(controls, tuple) or len(controls) < 3 or len(controls) > 32:
        raise OrientationEvidenceError("insufficient_independent_controls")
    if type(width) is not int or type(height) is not int or width < 2 or height < 2:
        raise OrientationEvidenceError("invalid_dimensions")
    if type(tolerance) not in (float, int) or not isfinite(tolerance) or tolerance <= 0:
        raise OrientationEvidenceError("invalid_tolerance")
    for item in controls:
        if (not isinstance(item, ControlPoint)
                or type(item.column) is not int or type(item.north_up_row) is not int
                or not 0 <= item.column < width or not 0 <= item.north_up_row < height
                or type(item.expected_raw_value) not in (int, float)
                or not isfinite(item.expected_raw_value)):
            raise OrientationEvidenceError("invalid_control")
    if len({(c.column, c.north_up_row) for c in controls}) != len(controls):
        raise OrientationEvidenceError("duplicate_control")
    # A single geographic band cannot independently establish north/south order.
    # Reject even-sized centre-line-only samples and one-sided witnesses.
    if (not any(c.north_up_row < height // 2 for c in controls)
            or not any(c.north_up_row >= (height + 1) // 2 for c in controls)):
        raise OrientationEvidenceError("insufficient_north_south_coverage")
    if len({c.column for c in controls}) < 2:
        raise OrientationEvidenceError("insufficient_east_west_coverage")
    try:
        import h5py
        with h5py.File(path, "r") as h:
            if dataset_path not in h or h[dataset_path].shape != (height, width):
                raise OrientationEvidenceError("shape_mismatch")
            ds = h[dataset_path]
            matches = []
            for north in (True, False):
                count = 0
                for control in controls:
                    y = control.north_up_row if north else height - control.north_up_row - 1
                    observed = float(ds[y, control.column])
                    if isfinite(observed) and abs(observed - control.expected_raw_value) <= tolerance:
                        count += 1
                matches.append(count)
    except OrientationEvidenceError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise OrientationEvidenceError("hdf5_controls_unreadable") from exc
    if matches[0] == len(controls) and matches[1] < len(controls):
        return OrientationFinding(True, matches[0], matches[1], verified=True)
    if matches[1] == len(controls) and matches[0] < len(controls):
        return OrientationFinding(False, matches[1], matches[0], verified=True)
    raise OrientationEvidenceError("orientation_ambiguous_or_mismatched")
