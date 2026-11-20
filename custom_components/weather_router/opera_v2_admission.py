"""Strict server-side OPERA RATE admission contract for existing Consumer V2.

The request may select a source but cannot grant scientific, security or
operational approvals. This gate is preparatory and defaults to NO-GO.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite


@dataclass(frozen=True)
class RateAdmission:
    geometry_verified: bool = False
    row_orientation_verified: bool = False
    original_pixel_positions_verified: bool = False
    quality_verified: bool = False
    palette_verified: bool = False
    native_runtime_verified: bool = False
    authenticated_tile_route_verified: bool = False
    valid_at: datetime | None = None
    source_id: str | None = None
    units: str = "mm/h"

    @property
    def ready(self) -> bool:
        checks = (
            self.geometry_verified,
            self.row_orientation_verified,
            self.original_pixel_positions_verified,
            self.quality_verified,
            self.palette_verified,
            self.native_runtime_verified,
            self.authenticated_tile_route_verified,
        )
        if any(flag is not True for flag in checks):
            return False
        if self.units != "mm/h" or self.source_id != "opera":
            return False
        instant = self.valid_at
        return isinstance(instant, datetime) and instant.tzinfo is not None


def explicit_rate_response(*, enabled: bool, correlation_id, capability: str,
                           source_request: dict, admission: RateAdmission | None = None) -> dict:
    """Nonpublishing V2 answer while actual frame and tile URL are unapproved.

    This guard deliberately does not convert readiness into an automatic
    positive result: publication also needs a registered, authenticated frame.
    """
    if source_request not in ({"provider_id": "opera", "product_id": "RATE"},
                              {"provider_id": "opera", "product_id": "RATE", "diagnostic": True}):
        raise ValueError("invalid_opera_source_request")
    if enabled is not True:
        status, reason = "disabled", "provider_disabled"
    else:
        status, reason = "active_blocked", "opera_raster_not_scientifically_approved"
    return {
        "contract_version": 2, "capability": capability,
        "source_request": dict(source_request),
        "provider_id": "opera", "product_id": "RATE",
        "source_id": None, "correlation_id": correlation_id,
        "status": status, "block_reason": reason,
        "raster_approved": False, "valid_at": None, "age_seconds": None,
        "layers": [], "tile_urls": [], "fallback_performed": False,
    }


def registered_rate_response(*, enabled: bool, correlation_id, capability: str,
                             source_request: dict, registry, stamp: str,
                             profile_authorized: bool, max_age_seconds: int, now: datetime | None = None) -> dict:
    """Expose a trusted registered RATE frame only after all server gates pass.

    The browser uses Bearer-authenticated fetch + Blob; URL contains no secret.
    This does not register the dormant HomeAssistantView or approve science.
    """
    denied = explicit_rate_response(enabled=enabled, correlation_id=correlation_id,
                                    capability=capability, source_request=source_request)
    if enabled is not True or profile_authorized is not True or registry is None:
        return denied
    if not isinstance(stamp, str):
        return denied
    from .opera_tile_access import assert_authorized, TileAccessDenied
    registration = registry.lookup("RATE", stamp)
    admission = registry.admitted("RATE", stamp)
    if registration is None or not isinstance(admission, RateAdmission) or not admission.ready:
        return denied
    frame = registration.frame
    if admission.valid_at != frame.valid_at:
        return denied
    try:
        assert_authorized(authenticated_user=True, profile_and_provider_allowed=True,
                          valid_at=frame.valid_at, now=now or datetime.now(timezone.utc),
                          max_age_seconds=max_age_seconds)
    except TileAccessDenied:
        return denied
    url = f"/api/weather_router/opera_tile/RATE/{stamp}/{{z}}/{{x}}/{{y}}.png"
    denied.update(status="active", block_reason=None, raster_approved=True,
                  source_id="opera", valid_at=frame.valid_at.astimezone(timezone.utc).isoformat(),
                  age_seconds=max(0, int(((now or datetime.now(timezone.utc)) - frame.valid_at).total_seconds())),
                  layers=[{"provider_id": "opera", "product_id": "RATE", "unit": "mm/h",
                           "render_mode": "raster_tile", "tile_url": url,
                           "attribution": registration.attribution}],
                  tile_urls=[url])
    return denied


def diagnostic_rate_response(*, enabled: bool, correlation_id, capability: str,
                             source_request: dict, registry, stamp: str,
                             admin_authorized: bool, now: datetime | None = None,
                             max_age_seconds: int = 1500) -> dict:
    """DEV-only labelled V2 response; NEVER scientifically approved."""
    denied = explicit_rate_response(enabled=enabled, correlation_id=correlation_id,
                                    capability=capability, source_request=source_request)
    if (source_request.get("diagnostic") is not True or enabled is not True
            or admin_authorized is not True or registry is None
            or not isinstance(stamp, str) or not registry.is_diagnostic("RATE", stamp)):
        return denied
    entry = registry.lookup("RATE", stamp)
    if entry is None:
        return denied
    from .opera_tile_access import assert_authorized, TileAccessDenied
    instant = now or datetime.now(timezone.utc)
    try:
        assert_authorized(authenticated_user=True, profile_and_provider_allowed=True,
                          valid_at=entry.frame.valid_at, now=instant, max_age_seconds=max_age_seconds)
    except TileAccessDenied as exc:
        if str(exc) == "stale_or_future":
            age = (instant.astimezone(timezone.utc) - entry.frame.valid_at.astimezone(timezone.utc)).total_seconds()
            denied.update(
                status="active_blocked",
                block_reason="opera_diagnostic_frame_expired" if age > max_age_seconds else "opera_diagnostic_frame_future",
                valid_at=entry.frame.valid_at.astimezone(timezone.utc).isoformat(),
                age_seconds=round(age, 2),
                max_age_seconds=max_age_seconds,
                diagnostic_only=False,
            )
        return denied
    url = f"/api/weather_router/opera_tile/RATE/{stamp}/{{z}}/{{x}}/{{y}}.png"
    denied.update(status="diagnostic_unverified", block_reason="scientific_evidence_missing",
                  raster_approved=False, source_id="opera",
                  valid_at=entry.frame.valid_at.astimezone(timezone.utc).isoformat(),
                  age_seconds=int((instant-entry.frame.valid_at).total_seconds()),
                  layers=[{"provider_id":"opera", "product_id":"RATE",
                           "render_mode":"raster_tile", "unit":"mm/h",
                           "scientific_status":"UNVERIFIED_DIAGNOSTIC",
                           "tile_url":url, "attribution":entry.attribution}],
                  tile_urls=[url], diagnostic_only=True)
    return denied
