"""Server-authorized OPERA RATE candidate for ordinary Consumer V2 routing.

The source inventory is derived from a trusted registered frame, not from a
browser's provider preference. Diagnostic registrations cannot enter routing.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from math import isfinite
from .opera_v2_admission import RateAdmission


def registered_rate_mosaic_source(registry, stamp, *, max_age_seconds, now=None, stale_after_seconds=None):
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
        return None
    if registry is None or not isinstance(stamp, str):
        return None
    try:
        frame = registry.lookup("RATE", stamp)
        admission = registry.admitted("RATE", stamp)
        diagnostic = registry.is_diagnostic("RATE", stamp)
    except (AttributeError, TypeError, ValueError):
        return None
    if (diagnostic or frame is None or not isinstance(admission, RateAdmission)
            or not admission.ready or admission.valid_at != frame.frame.valid_at):
        return None
    if not all((
        frame.quality_verified is True,
        frame.palette_verified is True,
        frame.raster_metadata_verified is True,
        frame.row_orientation_verified is True,
        frame.original_pixel_positions_verified is True,
        frame.unit == "mm/h",
    )):
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return None
    age = (current.astimezone(timezone.utc) -
           admission.valid_at.astimezone(timezone.utc)).total_seconds()
    if not 0 <= age <= max_age_seconds:
        return None
    corners = getattr(frame, "geographic_corners", None)
    if not isinstance(corners, dict) or set(corners) != {"LL", "LR", "UL", "UR"}:
        return None
    try:
        latitudes = [float(v[0]) for v in corners.values()]
        longitudes = [float(v[1]) for v in corners.values()]
    except (KeyError, TypeError, IndexError, ValueError):
        return None
    if not all(isfinite(v) for v in latitudes + longitudes):
        return None
    south, north = min(latitudes), max(latitudes)
    west, east = min(longitudes), max(longitudes)
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        return None
    mask = getattr(frame, "observation_mask", None)
    if mask is not None:
        if mask.generation != frame.frame.digest or datetime.fromisoformat(mask.valid_at) != admission.valid_at:
            return None
        west, east, south, north = (mask.hull[k] for k in ("west", "east", "south", "north"))
    valid_at = admission.valid_at.astimezone(timezone.utc).isoformat()
    tile_url = f"/api/weather_router/opera_tile/RATE/{stamp}/{{z}}/{{x}}/{{y}}.png"

    from .opera_rate_palette import rate_legend

    async def fetch():
        return {
            "tile_url": tile_url, "frame_time": valid_at,
            "attribution": "EUMETNET OPERA",
            "legend": rate_legend(),
            "tile_size": 256, "min_zoom": 0, "max_zoom": 16,
            "default_opacity": 0.7,
        }

    return {
        "source_id": "opera/opera_rate_raster",
        "eligible": True,
        "observation_mask": mask,
        "observation_valid_until": (admission.valid_at + timedelta(seconds=max_age_seconds)).isoformat(),
        "machine_coverage": {"scope": "bbox", "bbox": {
            "west": west, "east": east, "south": south, "north": north}},
        "semantics": {
            "quantity": "precipitation_rate", "unit": "mm/h",
            "measurement_method": "precipitation_rate_radar",
            "observation_kind": "observation"},
        "routing_score": (500, 500, 500),
        "async_fetch": fetch,
        "internal_authentication_required": True,
        "wr_max_age_seconds": max_age_seconds,
        "wr_stale_after_seconds": stale_after_seconds if stale_after_seconds is not None else max_age_seconds,
    }
