"""Pure strict preflight for a dormant authenticated OPERA image route.

No URL credentials, remote proxies, arbitrary files or provider registration.
This cannot replace Home Assistant's HTTP authentication or profile checks.
"""
from __future__ import annotations
from datetime import datetime, timezone
import re

class TileAccessDenied(ValueError):
    """Do not disclose whether a denied frame exists."""

_STAMP = re.compile(r"^\d{8}T\d{6}Z$")
_INTEGER = re.compile(r"^(?:0|[1-9]\d{0,5})$")

def validated_route(*, product: str, stamp: str, z: str, x: str, y: str, query_present: bool) -> tuple[int,int,int]:
    if query_present or product not in ("DBZH", "RATE") or not isinstance(stamp,str) or not _STAMP.fullmatch(stamp):
        raise TileAccessDenied("invalid_route")
    try:
        dt = datetime.strptime(stamp,"%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError as err:
        raise TileAccessDenied("invalid_stamp") from err
    if dt.strftime("%Y%m%dT%H%M%SZ") != stamp:
        raise TileAccessDenied("invalid_stamp")
    if any(not isinstance(v,str) or not _INTEGER.fullmatch(v) for v in (z,x,y)):
        raise TileAccessDenied("invalid_coordinates")
    z_int,x_int,y_int = int(z),int(x),int(y)
    if z_int > 16 or x_int >= (1 << z_int) or y_int >= (1 << z_int):
        raise TileAccessDenied("invalid_coordinates")
    return z_int,x_int,y_int

def assert_authorized(*, authenticated_user: object, profile_and_provider_allowed: bool,
                      valid_at: datetime, now: datetime) -> None:
    """Run BEFORE lookup, and AGAIN before response even on cached results.

    Caller supplies verified current server-side profile/permission decision.
    Never trust client-provided profiles or user IDs.
    """
    if authenticated_user is None or profile_and_provider_allowed is not True:
        raise TileAccessDenied("not_authorized")
    if not isinstance(valid_at,datetime) or not isinstance(now,datetime):
        raise TileAccessDenied("invalid_time")
    if valid_at.tzinfo is None or now.tzinfo is None:
        raise TileAccessDenied("invalid_time")
    age=(now.astimezone(timezone.utc)-valid_at.astimezone(timezone.utc)).total_seconds()
    if not 0 <= age <= 900:
        raise TileAccessDenied("stale_or_future")
