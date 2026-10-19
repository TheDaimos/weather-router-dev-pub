"""Pure fail-closed OPERA tile input policy. No provider or HTTP endpoint is activated."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import re
from typing import Any

FRAME_RE = re.compile(r"^OPERA@(\d{8})T(\d{4})@0@(DBZH|RATE)\.tiff$")
MAX_ZOOM = 16
MAX_FRAME_AGE = timedelta(seconds=900)
MAX_BYTES = 12 * 1024 * 1024

class TilePolicyError(ValueError):
    """Request is not a valid authorized tile descriptor."""

def normalized_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TilePolicyError("timezone_missing")
    return value.astimezone(timezone.utc)

def frame_id(filename: str, *, source_time: datetime, now: datetime) -> tuple[str, str]:
    """Filename is only a consistency check, never evidence of source time."""
    if not isinstance(filename, str) or not (match := FRAME_RE.fullmatch(filename)):
        raise TilePolicyError("invalid_product_filename")
    try:
        listed = datetime.strptime(match[1] + match[2], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise TilePolicyError("invalid_frame_clock") from exc
    data_time, clock = normalized_utc(source_time), normalized_utc(now)
    if listed != data_time:
        raise TilePolicyError("source_time_mismatch")
    if data_time > clock or clock - data_time > MAX_FRAME_AGE:
        raise TilePolicyError("frame_stale_or_future")
    return match[3], data_time.strftime("%Y%m%dT%H%M%SZ")

def validate_tile(z: Any, x: Any, y: Any) -> tuple[int, int, int]:
    if any(type(value) is not int for value in (z, x, y)):
        raise TilePolicyError("tile_coordinate_type")
    if not 0 <= z <= MAX_ZOOM or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise TilePolicyError("tile_out_of_bounds")
    return z, x, y

def validate_object_size(byte_size: Any) -> int:
    if type(byte_size) is not int or not 0 < byte_size <= MAX_BYTES:
        raise TilePolicyError("object_size_exceeded")
    return byte_size

def tile_cache_key(*, filename: str, source_time: datetime, now: datetime,
                   z: int, x: int, y: int, palette_version: str, quality_version: str) -> tuple[str, ...]:
    product, frame = frame_id(filename, source_time=source_time, now=now)
    validate_tile(z, x, y)
    if not all(isinstance(v, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", v)
               for v in (palette_version, quality_version)):
        raise TilePolicyError("unverified_style_revision")
    return (product, frame, str(z), str(x), str(y), palette_version, quality_version)
