"""Authenticated Home Assistant OPERA tile view.

Regular admitted RATE uses Home Assistant's authenticated transport contract.
Legacy diagnostic registrations additionally require HTTPS. Never a public S3 proxy.
Clients must use an authenticated fetch with Authorization header and an
in-memory image blob; a plain HTML <img src> cannot send Bearer credentials.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from time import monotonic
from typing import Callable

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .opera_frame_cache import VerifiedFrame
from .opera_tile_access import TileAccessDenied, assert_authorized, validated_route
from .opera_cog_tiles import OperaRasterError, render_verified_cog
from .opera_odim_png import OperaOdimPngError, render_verified_odim_rate

@dataclass(frozen=True)
class TileRegistration:
    """Internal trusted registration, never derived from URL or user input."""
    frame: VerifiedFrame
    unit: str
    palette: Callable[[float], tuple[int, int, int, int]]
    palette_verified: bool
    attribution: str
    quality_verified: bool = False
    raster_metadata_verified: bool = False

@dataclass(frozen=True)
class OdimRateTileRegistration(TileRegistration):
    grid: object = None
    projection: str = ""
    dataset_path: str = ""
    row_orientation_verified: bool = False
    original_pixel_positions_verified: bool = False
    geographic_corners: dict | None = None
    observation_mask: object = field(default=None, compare=False, repr=False)

def _record_tile(hass, *, outcome: str, details: dict) -> None:
    """Failure-isolated, bounded diagnostic recording for the existing tile route."""
    try:
        from .diagnostic_center import record
        record(hass, category="raster", outcome=outcome, details=details)
    except Exception:
        # Observability must never alter HTTP auth or pixel safety decisions.
        pass


class OperaTileView(HomeAssistantView):
    """Authenticated read-only image route with server-owned frame policies."""
    url = "/api/weather_router/opera_tile/{product}/{stamp}/{z}/{x}/{y}.png"
    name = "api:weather_router:opera_tile"
    requires_auth = True
    cors_allowed = False

    def __init__(self, hass, *, registry_lookup, is_permitted, is_enabled=None,
                 is_provider_enabled=None,
                 max_active: int = 2, wait_seconds: float = 0.2,
                 render_seconds: float = 3.0, max_waiting: int = 16,
                 is_diagnostic=None, max_age_seconds=None):
        if type(max_active) is not int or not 1 <= max_active <= 3:
            raise ValueError("invalid_parallel_budget")
        if not 0 < wait_seconds <= 1 or not 0 < render_seconds <= 10:
            raise ValueError("invalid_timeout")
        if type(max_waiting) is not int or not 1 <= max_waiting <= 64:
            raise ValueError("invalid_queue_budget")
        self.hass = hass
        self._registry_lookup = registry_lookup
        self._is_permitted = is_permitted
        self._is_enabled = is_enabled or (lambda: False)
        self._is_provider_enabled = is_provider_enabled or (lambda: False)
        self._is_diagnostic = is_diagnostic or (lambda product, stamp: False)
        # Read the current server-owned Config Entry setting for every request.
        # Fallback preserves the operational age limit for non-preview callers.
        from .opera_preview_age_policy import DEFAULT_PREVIEW_MAX_AGE_SECONDS
        self._max_age_seconds = max_age_seconds or (lambda: DEFAULT_PREVIEW_MAX_AGE_SECONDS)
        self._limit = asyncio.Semaphore(max_active)
        # Bound concurrent slot-acquisition attempts as well as live workers.
        # Each counter transition is synchronous within the HA event loop;
        # cancellation and timeout always decrement it via finally.
        self._max_waiting, self._waiting = max_waiting, 0
        self._wait_seconds, self._render_seconds = wait_seconds, render_seconds

    def _deny(self, code: str, phase: str, *, status: int = 403):
        # Fixed, bounded enum values only; never record request-derived values.
        _record_tile(self.hass, outcome="failed", details={
            "http_status": status, "tile_denial_code": code, "tile_denial_phase": phase,
        })
        headers = {"X-WeatherRouter-Tile-Denial": code,
                   "Cache-Control": "no-store, private"}
        if status == 401:
            raise web.HTTPUnauthorized(headers=headers)
        raise web.HTTPForbidden(headers=headers)

    def _policy(self, request, user, product, stamp, frame, diagnostic, phase):
        if (diagnostic or product != "RATE") and not request.secure:
            self._deny("insecure_transport", phase)
        if not self._is_enabled():
            self._deny("diagnostic_route_disabled", phase)
        if user is None:
            self._deny("missing_authenticated_user", phase, status=401)
        # Diagnostic registrations require administrator rights; normal
        # scientifically admitted frames use ordinary authenticated access.
        if diagnostic and getattr(user, "is_admin", False) is not True:
            self._deny("administrator_required", phase)
        if product != "RATE" and getattr(user, "is_admin", False) is not True:
            self._deny("administrator_required", phase)
        if not self._is_provider_enabled():
            self._deny("provider_disabled", phase)
        if self._is_permitted(user, product) is not True:
            self._deny("profile_not_authorized", phase)
        if diagnostic and self._is_diagnostic(product, stamp) is not True:
            self._deny("diagnostic_registration_revoked", phase)
        try:
            assert_authorized(authenticated_user=user,
                              profile_and_provider_allowed=True,
                              valid_at=frame.valid_at, now=datetime.now(timezone.utc),
                              max_age_seconds=self._max_age_seconds())
        except TileAccessDenied as exc:
            code = ("frame_expired" if str(exc) == "stale_or_future" and
                    datetime.now(timezone.utc) > frame.valid_at.astimezone(timezone.utc) else
                    "frame_in_future" if str(exc) == "stale_or_future" else
                    "invalid_frame_time")
            self._deny(code, phase)

    async def get(self, request: web.Request, product: str, stamp: str,
                  z: str, x: str, y: str) -> web.Response:
        phase = "before_registration"
        # Admitted RATE follows HA's HTTP authentication policy, including LAN
        # HTTP and TLS termination. The diagnostic gate is checked after lookup;
        # never infer security from client-supplied forwarded headers.
        if product != "RATE" and not request.secure:
            self._deny("insecure_transport", phase)
        if not self._is_enabled():
            self._deny("diagnostic_route_disabled", phase)
        user = request.get("hass_user")
        if user is None:
            self._deny("missing_authenticated_user", phase, status=401)
        if not self._is_provider_enabled():
            self._deny("provider_disabled", phase)
        if self._is_permitted(user, product) is not True:
            self._deny("profile_not_authorized", phase)
        try:
            z_num, x_num, y_num = validated_route(
                product=product, stamp=stamp, z=z, x=x, y=y,
                query_present=bool(request.query),
            )
        except TileAccessDenied:
            self._deny("invalid_route_or_stamp", phase)
        entry = self._registry_lookup(product, stamp)
        if not isinstance(entry, TileRegistration):
            self._deny("frame_not_registered", phase)
        frame = entry.frame
        if not isinstance(frame, VerifiedFrame) or frame.product != product:
            self._deny("frame_not_registered", phase)
        if frame.valid_at.strftime("%Y%m%dT%H%M%SZ") != stamp:
            self._deny("stamp_mismatch", phase)
        diagnostic = self._is_diagnostic(product, stamp) is True
        if (not diagnostic and not entry.palette_verified) or (product == "DBZH" and entry.unit != "dBZ") or (product == "RATE" and entry.unit != "mm/h"):
            self._deny("scientific_admission_missing", phase)
        # An unverified registration must never be rendered as an approved tile.
        # Diagnostic registration remains separately administrator-gated.
        if (not diagnostic and isinstance(entry, OdimRateTileRegistration)
                and (entry.row_orientation_verified is not True
                     or entry.original_pixel_positions_verified is not True)):
            self._deny("scientific_admission_missing", phase)
        if not diagnostic and (entry.quality_verified is not True or entry.raster_metadata_verified is not True):
            self._deny("scientific_admission_missing", phase)
        if isinstance(entry, OdimRateTileRegistration):
            if (product != "RATE" or (not diagnostic and entry.row_orientation_verified is not True)
                    or (not diagnostic and entry.original_pixel_positions_verified is not True)
                    or entry.grid is None or not entry.projection or not entry.dataset_path):
                self._deny("scientific_admission_missing", phase)
        if not entry.attribution.strip():
            self._deny("missing_attribution", phase)
        self._policy(request, user, product, stamp, frame, diagnostic, phase)

        if self._waiting >= self._max_waiting:
            _record_tile(self.hass, outcome="failed", details={"http_status":503})
            raise web.HTTPServiceUnavailable()
        self._waiting += 1
        try:
            try:
                await asyncio.wait_for(self._limit.acquire(),timeout=self._wait_seconds)
            except asyncio.TimeoutError as exc:
                _record_tile(self.hass, outcome="failed",
                          details={"http_status": 503, "timeout": True})
                raise web.HTTPServiceUnavailable() from exc
        finally:
            # A waiting client's cancellation must not leak a queue place.
            self._waiting -= 1

        # Recheck all mutable gates after queueing, before CPU work.
        try:
            self._policy(request, user, product, stamp, frame, diagnostic, "before_render")
        except (web.HTTPForbidden, web.HTTPUnauthorized):
            self._limit.release()
            raise

        # Keep semaphore occupied until the worker is ACTUALLY finished, even
        # after request cancellation or a response deadline.
        if isinstance(entry, OdimRateTileRegistration):
            work = partial(
                render_verified_odim_rate, trusted_path=frame.path,
                expected_sha256=frame.digest, grid=entry.grid,
                projection=entry.projection, dataset_path=entry.dataset_path,
                x=x_num, y=y_num, z=z_num,
                orientation_verified=entry.row_orientation_verified is True,
            )
        else:
            work = partial(
                render_verified_cog, trusted_path=frame.path,
                expected_sha256=frame.digest,z=z_num,x=x_num,y=y_num,
                palette=entry.palette, verified_frame=frame,
            )
        render_started = monotonic()
        try:
            task = asyncio.ensure_future(self.hass.async_add_executor_job(work))
        except Exception:
            self._limit.release()
            raise
        def _worker_finished(completed):
            # The worker retains its slot until termination. Retrieve its late
            # exception even when the HTTP request timed out or was cancelled.
            try:
                if not completed.cancelled():
                    error = completed.exception()
                    if error is not None:
                        _record_tile(self.hass, outcome="failed",
                                     details={"http_status": 503, "worker_failed": True})
            finally:
                self._limit.release()
        task.add_done_callback(_worker_finished)
        try:
            png = await asyncio.wait_for(asyncio.shield(task),timeout=self._render_seconds)
        except asyncio.TimeoutError as exc:
            _record_tile(self.hass, outcome="failed",
                      details={"http_status": 503, "timeout": True})
            raise web.HTTPServiceUnavailable() from exc
        except (OperaRasterError, OperaOdimPngError, OSError, ValueError) as exc:
            _record_tile(self.hass, outcome="failed", details={"http_status": 503})
            raise web.HTTPServiceUnavailable() from exc

        # SCI-06: a frame revoked/replaced during executor rendering is no
        # longer authorized for delivery, even when its old user policy passes.
        if (self._registry_lookup(product, stamp) is not entry
                or (diagnostic and self._is_diagnostic(product, stamp) is not True)):
            self._deny("frame_registration_revoked", "before_delivery")
        # Verify mutable policies again immediately before returning pixels.
        self._policy(request, user, product, stamp, frame, diagnostic, "before_delivery")
        if not isinstance(png,bytes) or not 0 < len(png) <= 512 * 1024:
            _record_tile(self.hass, outcome="failed", details={"http_status": 503})
            raise web.HTTPServiceUnavailable()
        # Only an authenticated, finally authorized PNG response is counted.
        # No coordinates, source paths or identifiers enter the diagnostic ring.
        _record_tile(self.hass, outcome="success",
                  details={"response_bytes": len(png), "http_status": 200,
                           "duration_ms": round((monotonic() - render_started) * 1000, 2)})
        return web.Response(
            body=png,content_type="image/png",
            headers={
                "Cache-Control":"no-store, private",
                "X-Content-Type-Options":"nosniff",
                "X-WeatherRouter-Product":product,
                "X-WeatherRouter-Scientific-Status": "unverified-diagnostic" if diagnostic else "approved",
            },
        )
