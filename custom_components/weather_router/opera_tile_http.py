"""Dormant authenticated Home Assistant OPERA tile view.

Not registered with hass.http until GR browser authentication, source policies,
product palette and actual HA runtime are proven. Never a public S3 proxy.
Clients must use an authenticated fetch with Authorization header and an
in-memory image blob; a plain HTML <img src> cannot send Bearer credentials.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from typing import Callable

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .opera_frame_cache import VerifiedFrame
from .opera_tile_access import TileAccessDenied, assert_authorized, validated_route
from .opera_cog_tiles import OperaRasterError, render_verified_cog

@dataclass(frozen=True)
class TileRegistration:
    """Internal trusted registration, never derived from URL or user input."""
    frame: VerifiedFrame
    unit: str
    palette: Callable[[float], tuple[int, int, int, int]]
    palette_verified: bool
    attribution: str

class OperaTileView(HomeAssistantView):
    """Authenticated read-only image route, disabled until explicitly staged."""
    url = "/api/weather_router/opera_tile/{product}/{stamp}/{z}/{x}/{y}.png"
    name = "api:weather_router:opera_tile"
    requires_auth = True
    cors_allowed = False

    def __init__(self, hass, *, registry_lookup, is_permitted, is_enabled=None,
                 max_active: int = 2, wait_seconds: float = 0.2,
                 render_seconds: float = 3.0):
        if type(max_active) is not int or not 1 <= max_active <= 3:
            raise ValueError("invalid_parallel_budget")
        if not 0 < wait_seconds <= 1 or not 0 < render_seconds <= 10:
            raise ValueError("invalid_timeout")
        self.hass = hass
        self._registry_lookup = registry_lookup
        self._is_permitted = is_permitted
        self._is_enabled = is_enabled or (lambda: False)
        self._limit = asyncio.Semaphore(max_active)
        self._wait_seconds, self._render_seconds = wait_seconds, render_seconds

    async def get(self, request: web.Request, product: str, stamp: str,
                  z: str, x: str, y: str) -> web.Response:
        # Browser use: authenticated fetch + Blob. No URL bearer/authSig/cookie.
        if not self._is_enabled() or not request.secure:
            raise web.HTTPForbidden()
        user = request.get("hass_user")
        if user is None:
            raise web.HTTPUnauthorized()
        try:
            z_num, x_num, y_num = validated_route(
                product=product,stamp=stamp,z=z,x=x,y=y,
                query_present=bool(request.query),
            )
            # Explicitly query current server-side policy; never use consumer,
            # profile or user strings from URL. Check BEFORE registry lookup.
            permitted = self._is_permitted(user, product)
            if permitted is not True:
                raise TileAccessDenied("not_authorized")
            entry = self._registry_lookup(product, stamp)
            if not isinstance(entry, TileRegistration):
                raise TileAccessDenied("unregistered_frame")
            frame = entry.frame
            if not isinstance(frame, VerifiedFrame) or frame.product != product:
                raise TileAccessDenied("unregistered_frame")
            if frame.valid_at.strftime("%Y%m%dT%H%M%SZ") != stamp:
                raise TileAccessDenied("frame_time_mismatch")
            if not entry.palette_verified or (
                product == "DBZH" and entry.unit != "dBZ"
            ) or (product == "RATE" and entry.unit != "mm/h"):
                raise TileAccessDenied("product_semantics_unverified")
            if not entry.attribution.strip():
                raise TileAccessDenied("missing_attribution")
            assert_authorized(
                authenticated_user=user, profile_and_provider_allowed=permitted,
                valid_at=frame.valid_at,now=datetime.now(timezone.utc),
            )
        except TileAccessDenied as exc:
            raise web.HTTPForbidden() from exc

        try:
            await asyncio.wait_for(self._limit.acquire(),timeout=self._wait_seconds)
        except asyncio.TimeoutError as exc:
            raise web.HTTPServiceUnavailable() from exc

        # Keep semaphore occupied until the worker is ACTUALLY finished, even
        # after request cancellation or a response deadline.
        work = partial(
            render_verified_cog, trusted_path=frame.path,
            expected_sha256=frame.digest,z=z_num,x=x_num,y=y_num,
            palette=entry.palette, verified_frame=frame,
        )
        try:
            task = asyncio.ensure_future(self.hass.async_add_executor_job(work))
        except Exception:
            self._limit.release()
            raise
        task.add_done_callback(lambda completed: self._limit.release())
        try:
            png = await asyncio.wait_for(asyncio.shield(task),timeout=self._render_seconds)
        except asyncio.TimeoutError as exc:
            raise web.HTTPServiceUnavailable() from exc
        except (OperaRasterError, OSError, ValueError) as exc:
            raise web.HTTPServiceUnavailable() from exc

        # Recheck permission and source-time even for future pixel-cache hits,
        # after rendering and before every HTTP response.
        try:
            assert_authorized(
                authenticated_user=user,
                profile_and_provider_allowed=self._is_permitted(user,product),
                valid_at=frame.valid_at,now=datetime.now(timezone.utc),
            )
            if not self._is_enabled():
                raise TileAccessDenied("disabled")
        except TileAccessDenied as exc:
            raise web.HTTPForbidden() from exc
        if not isinstance(png,bytes) or not 0 < len(png) <= 512 * 1024:
            raise web.HTTPServiceUnavailable()
        return web.Response(
            body=png,content_type="image/png",
            headers={
                "Cache-Control":"no-store, private",
                "X-Content-Type-Options":"nosniff",
                "X-WeatherRouter-Product":product,
            },
        )
