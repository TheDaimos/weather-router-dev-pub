"""Strict product metadata contracts for dormant OPERA RATE/DBZH CoG images.

No provider registration, URL construction, product conversion or approved
colour/quality interpretation. Source timestamps must already be normalized
through the WeatherRouter central UTC time contract before this check.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import PurePath
from types import MappingProxyType

from .opera_tile_security import FRAME_RE, TilePolicyError, normalized_utc


class OperaProductError(ValueError):
    """Untrusted or mismatching scientific raster contract."""


@dataclass(frozen=True)
class ProductContract:
    code: str
    unit: str
    width: int
    height: int
    resolution_m: int
    cadence_minutes: int
    attribution: str


_PRODUCTS = MappingProxyType({
    "DBZH": ProductContract(
        "DBZH", "dBZ", 3800, 4400, 1000, 5,
        "EUMETNET OPERA CIRRUS · CC BY 4.0"),
    "RATE": ProductContract(
        "RATE", "mm/h", 1900, 2200, 2000, 15,
        "EUMETNET OPERA NIMBUS · CC BY 4.0"),
})


@dataclass(frozen=True)
class CheckedRaster:
    """Geometry and measurement metadata only; NOT publishable quality proof."""
    product: ProductContract
    valid_at: datetime
    quality_status: str = "unverified"
    palette_status: str = "unverified"

    @property
    def ready_for_public_tiles(self) -> bool:
        return False


def _close(actual, required: float) -> bool:
    return type(actual) in (float, int) and isfinite(actual) and abs(actual-required) <= 1e-5


def check_opera_raster(*, filename: str, valid_at: datetime, dataset) -> CheckedRaster:
    """Check trusted opened raster without interpreting quality1 or its colours.

    Validate physical dimensions, two scientific bands, and exact known OPERA
    LAEA parameterization. Reject a valid-looking TIFF with wrong physics.
    Does not assert that the filename establishes measurement time.
    """
    if not isinstance(filename, str) or filename != PurePath(filename).name:
        raise OperaProductError("invalid_filename")
    match = FRAME_RE.fullmatch(filename)
    if not match:
        raise OperaProductError("unknown_opera_object")
    try:
        code = match.group(3)
        contract = _PRODUCTS[code]
        frame_time = datetime.strptime(match.group(1)+match.group(2), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        normalized = normalized_utc(valid_at)
    except (KeyError, ValueError, TypeError, TilePolicyError) as exc:
        raise OperaProductError("invalid_time_contract") from exc
    if frame_time != normalized:
        raise OperaProductError("source_clock_mismatch")
    # Real OPERA product cadence; no inference from HTTP retrieval times.
    if frame_time.minute % contract.cadence_minutes != 0:
        raise OperaProductError("cadence_mismatch")
    if (getattr(dataset, "driver", None) != "GTiff"
            or dataset.width != contract.width or dataset.height != contract.height
            or dataset.count != 2):
        raise OperaProductError("raster_geometry_mismatch")
    crs = getattr(dataset, "crs", None)
    if crs is None or not callable(getattr(crs, "to_dict", None)):
        raise OperaProductError("missing_crs")
    params = crs.to_dict()
    if params.get("proj") != "laea":
        raise OperaProductError("unexpected_projection")
    for key, number in (("lat_0",55),("lon_0",10),("x_0",1950000),("y_0",-2100000)):
        if not _close(params.get(key),number):
            raise OperaProductError("projection_parameters_mismatch")
    transform = getattr(dataset, "transform", None)
    if transform is None or not all((
        _close(transform.a, contract.resolution_m),
        _close(transform.e, -contract.resolution_m),
        _close(transform.b, 0),
        _close(transform.d, 0),
    )):
        raise OperaProductError("pixel_resolution_mismatch")
    # NoData -9999000 is not precipitation zero and does not replace NaN.
    if not _close(dataset.nodata, -9999000):
        raise OperaProductError("nodata_mismatch")
    descriptions = getattr(dataset, "descriptions", ())
    if not isinstance(descriptions, (tuple,list)) or len(descriptions) != 2:
        raise OperaProductError("band_inventory_missing")
    for actual, expected in zip(descriptions,(code,"quality1")):
        if actual is not None and actual.lower() != expected.lower():
            raise OperaProductError("band_semantics_mismatch")
    if getattr(dataset, "dtypes", None) != ("float32", "float32"):
        raise OperaProductError("band_dtype_mismatch")
    # No known numerical interpretation of quality1 is approved yet.
    return CheckedRaster(contract, normalized)
