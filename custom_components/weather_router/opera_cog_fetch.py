"""Dormant, bounded HTTPS acquisition for approved OPERA CoGs.

Uses an existing Home Assistant aiohttp session supplied by the caller; no
open proxy, no externally supplied URL, no redirects or user-controlled path.
Admission to the existing immutable frame cache happens in HA's executor.
No provider registration and no interpretation of source timestamps.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import partial
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import aiohttp

from .opera_tile_security import frame_id, normalized_utc, MAX_BYTES

# Hardcoded, previously independently confirmed public OPERA collection.
OPERA_BUCKET = "https://s3.waw3-1.cloudferro.com/openradar-24h"
MAX_ACTIVE_DOWNLOADS = 2
DOWNLOAD_DEADLINE_SECONDS = 10
READ_CHUNK_BYTES = 65536


class OperaDownloadError(ValueError):
    """A source acquisition failed closed; never include URL/secret in text."""


def object_url(*, filename: str, valid_at: datetime, now: datetime) -> str:
    """Build only the known bucket/date/product key, after trusted UTC checks."""
    try:
        product, stamp = frame_id(filename, source_time=valid_at, now=now)
    except (ValueError, TypeError) as exc:
        raise OperaDownloadError("unapproved_source_frame") from exc
    date = normalized_utc(valid_at)
    # Filename has already passed the anchored product-only name contract.
    return (
        f"{OPERA_BUCKET}/{date:%Y/%m/%d}/OPERA/COMP/{filename}"
    )


def _store_frame(cache, payload: bytes, product: str, valid_at: datetime, digest: str):
    """Worker thread only: one copy into the existing secure frame admission."""
    with TemporaryDirectory(prefix="wr-opera-download-") as temporary:
        path = Path(temporary) / "frame.tiff"
        path.write_bytes(payload)
        return cache.admit(
            source_path=path, product=product, valid_at=valid_at,
            expected_sha256=digest,
        )


class OperaCogFetch:
    """Per-instance bounded fetcher. Caller must keep one instance per router."""

    def __init__(self, *, hass, session, cache, max_active: int = MAX_ACTIVE_DOWNLOADS, clock=None):
        if type(max_active) is not int or not 1 <= max_active <= MAX_ACTIVE_DOWNLOADS:
            raise ValueError("invalid_fetch_concurrency")
        self.hass = hass
        self.session = session
        self.cache = cache
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._slots = asyncio.Semaphore(max_active)

    async def fetch(self, *, filename: str, valid_at: datetime, now: datetime):
        url = object_url(filename=filename, valid_at=valid_at, now=now)
        product, _ = frame_id(filename, source_time=valid_at, now=now)
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=0.2)
        except asyncio.TimeoutError as exc:
            raise OperaDownloadError("provider_network_budget_exhausted") from exc
        worker_submitted = False
        try:
            # Timeout applies to the bounded network read, not native worker
            # admission. The semaphore is held until a submitted worker ends.
            async with asyncio.timeout(DOWNLOAD_DEADLINE_SECONDS):
                async with self.session.get(
                    url,
                    headers={"Accept": "application/octet-stream", "Accept-Encoding": "identity"},
                    timeout=aiohttp.ClientTimeout(total=DOWNLOAD_DEADLINE_SECONDS),
                    allow_redirects=False,
                    ssl=True,
                ) as response:
                    if response.status != 200:
                        raise OperaDownloadError("unavailable_or_redirect")
                    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    if content_type not in (
                        "binary/octet-stream", "application/octet-stream",
                        "image/tiff", "image/geotiff", "application/x-tiff",
                    ):
                        raise OperaDownloadError("unexpected_content_type")
                    length = response.headers.get("Content-Length")
                    if length is not None:
                        try:
                            reported = int(length)
                        except ValueError as exc:
                            raise OperaDownloadError("invalid_length") from exc
                        if not 0 < reported <= MAX_BYTES:
                            raise OperaDownloadError("oversized_object")
                    payload = bytearray()
                    async for block in response.content.iter_chunked(READ_CHUNK_BYTES):
                        if not block:
                            continue
                        if len(payload) + len(block) > MAX_BYTES:
                            raise OperaDownloadError("oversized_stream")
                        payload.extend(block)
                    if length is not None and len(payload) != reported:
                        raise OperaDownloadError("incomplete_object")
            if len(payload) < 8 or bytes(payload[:4]) not in (
                b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+",
            ):
                raise OperaDownloadError("not_a_tiff")
            # Critical: snapshot age is checked again after download activity.
            frame_id(filename, source_time=valid_at, now=self._clock())
            digest = sha256(payload).hexdigest()
            worker = partial(
                _store_frame, self.cache, bytes(payload), product,
                normalized_utc(valid_at), digest,
            )
            task = asyncio.ensure_future(self.hass.async_add_executor_job(worker))
            worker_submitted = True
            task.add_done_callback(lambda completed: self._slots.release())
            # Cancellation cannot release the concurrency slot early:
            # only the finished admission worker frees the slot.
            return await asyncio.shield(task)
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            raise OperaDownloadError("source_timeout_or_network_failure") from exc
        finally:
            if not worker_submitted:
                self._slots.release()
