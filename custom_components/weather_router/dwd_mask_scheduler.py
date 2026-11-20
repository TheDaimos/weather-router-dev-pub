"""Background preparation of current DWD radar NoData masks for WR V2.

Never holds a consumer response or a second provider waiting on DWD WCS.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import struct
import time

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .dwd_frame_mask import DWD_RADAR, _stamp, cached_mask
from .dwd_mask_auto import MAX_TIFF_BYTES, decode_mask, read_tiff_chunks, stage_mask, wcs_url

OPERA_RATE = "opera/opera_rate_raster"
_current_tasks = {}
_retry_after = {}


def maybe_schedule_dwd_mask(hass, result, directory):
    """Start one bounded WCS fetch only for a concurrently admitted DWD+OPERA frame."""
    if directory is None or not isinstance(result, dict):
        return "not_configured"
    layers = result.get("layers") or ()
    dwd = next((row for row in layers if row.get("source_id") == DWD_RADAR), None)
    opera = next((row for row in layers if row.get("source_id") == OPERA_RATE), None)
    if not dwd or not opera:
        return "not_admitted"
    if dwd.get("dwd_nodata_mask"):
        return "verified"
    status = result.get("spatial_planning", {}).get("dwd_validity")
    if status is None:
        _, status = cached_mask(directory, dwd)
    if status not in ("missing", "invalid", "frame_mismatch"):
        return status
    try:
        stamp = _stamp(dwd["times"]["valid_at"])
        age = datetime.now(timezone.utc).timestamp() - stamp
        if age < -120 or age > 1800:
            return "outside_recent_analysis"
    except (ValueError, KeyError, TypeError):
        return "invalid_frame"
    loop = asyncio.get_running_loop()
    task_key = (id(loop), str(Path(directory)), stamp)
    existing = _current_tasks.get(task_key)
    if existing is not None and not existing.done():
        return "preparing"
    if time.monotonic() < _retry_after.get(task_key, 0):
        return "retry_backoff"
    _retry_after[task_key] = time.monotonic() + 300

    async def prepare():
        try:
            session = async_get_clientsession(hass)
            timeout = aiohttp.ClientTimeout(total=30, connect=8)
            async with session.get(wcs_url(dwd["times"]["valid_at"]),
                                   timeout=timeout, allow_redirects=False) as response:
                if response.status != 200 or response.content_length and response.content_length > MAX_TIFF_BYTES:
                    return
                if response.headers.get("Content-Type", "").split(";", 1)[0].lower() not in (
                    "image/tiff", "image/geotiff", "application/octet-stream"):
                    return
                payload = await read_tiff_chunks(response.content.iter_chunked(64 * 1024))
            mask = await hass.async_add_executor_job(decode_mask, payload, dwd["times"]["valid_at"])
            await hass.async_add_executor_job(stage_mask, directory, mask)
            hass.bus.async_fire("weather_router_routing_changed", {"dwd_mask_ready": True})
        except (asyncio.TimeoutError, OSError, ValueError, KeyError, IndexError,
                TypeError, struct.error,
                aiohttp.ClientError):
            # Independently failing DWD WCS may never change the source decision.
            return

    for key, deadline in tuple(_retry_after.items()):
        if deadline <= time.monotonic() and key not in _current_tasks:
            _retry_after.pop(key)
    task = loop.create_task(prepare(), name="weather_router_dwd_validity")
    _current_tasks[task_key] = task
    task.add_done_callback(lambda done: _current_tasks.pop(task_key, None))
    return "preparing"
