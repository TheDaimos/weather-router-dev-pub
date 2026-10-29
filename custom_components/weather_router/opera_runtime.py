"""Public OPERA server-owned diagnostic runtime; strictly not a scientific release.

Rate/DBZH/ACRR are separate contracts. No downloader, HTTP route or Consumer
registration is activated by creating this runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from pathlib import Path
from .opera_cycle_store import CycleJournal, CycleStoreError

from .opera_frame_cache import ImmutableFrameCache, VerifiedFrame, FrameCacheError
from .opera_tile_http import TileRegistration

PRODUCTS = ("RATE", "DBZH", "ACRR")
UNITS = {"RATE": "mm/h", "DBZH": "dBZ", "ACRR": "mm"}
DEFAULT_MAX_AGE_SECONDS = 1500
MAX_HISTORICAL_SECONDS = 3600


def utc_status(observed_at, *, now=None, max_age_seconds=DEFAULT_MAX_AGE_SECONDS,
               stale_after_seconds=DEFAULT_MAX_AGE_SECONDS, serve_stale=False):
    """UTC observation age, never download or admission time."""
    if (not isinstance(observed_at, datetime) or observed_at.tzinfo is None
            or type(max_age_seconds) is not int or not 900 <= max_age_seconds <= 3600
            or type(stale_after_seconds) is not int or not 900 <= stale_after_seconds <= 3600
            or type(serve_stale) is not bool):
        return "UNAVAILABLE"
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None:
        return "UNAVAILABLE"
    age = (now.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds()
    if not 0 <= age <= (MAX_HISTORICAL_SECONDS if serve_stale else max_age_seconds):
        return "UNAVAILABLE"
    return "STALE" if age > min(max_age_seconds, stale_after_seconds) else "CURRENT"


@dataclass(frozen=True)
class PreparedCycle:
    product: str
    registration: TileRegistration
    stamp: str
    digest: str


class RateTileRegistry:
    """Atomic per-product active generations with immutable registrations.

    Old registrations remain addressable only while they are the active stamp.
    A reader that already leased a file can finish independently of promotion.
    """
    def __init__(self):
        self._lock = RLock()
        self._active: dict[str, PreparedCycle] = {}

    def lookup(self, product, stamp):
        with self._lock:
            cycle = self._active.get(product)
            if cycle is not None and cycle.stamp == stamp:
                return cycle.registration
            return None

    def active(self, product):
        with self._lock:
            return self._active.get(product)

    def promote(self, candidate: PreparedCycle):
        if not isinstance(candidate, PreparedCycle) or candidate.product not in PRODUCTS:
            raise ValueError("invalid_cycle")
        frame = candidate.registration.frame
        if (frame.product != candidate.product or candidate.digest != frame.digest
                or candidate.stamp != frame.valid_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")):
            raise ValueError("inconsistent_cycle")
        with self._lock:
            old = self._active.get(candidate.product)
            if old:
                if candidate.stamp < old.stamp:
                    raise ValueError("older_cycle")
                if candidate.stamp == old.stamp:
                    if candidate.digest != old.digest:
                        raise ValueError("conflicting_cycle")
                    return old.stamp
            self._active[candidate.product] = candidate
            return candidate.stamp

    def revoke(self):
        with self._lock:
            self._active.clear()


class OperaRuntime:
    """One shared cache, one atomic registry, server-owned and disabled by default."""
    def __init__(self, *, journal_root=None):
        self.cache = ImmutableFrameCache(max_frames=3)
        self.journal = CycleJournal(journal_root) if journal_root is not None else None
        self.last_error = None
        self.last_promotion_utc = None
        self.registry = RateTileRegistry()
        self._lock = RLock()
        self.enabled = False
        self.services = {product: False for product in PRODUCTS}
        self._closed = False

    def prepare(self, *, source_path, product, valid_at, digest,
                palette, attribution, quality_verified=False,
                raster_metadata_verified=False, palette_verified=False):
        """Stage only a correctly typed source; no visibility until promote()."""
        if product not in ("RATE", "DBZH"):
            # ACRR requires its own independent native raster validator.
            raise ValueError("product_pipeline_unverified")
        if not isinstance(attribution, str) or not attribution.strip():
            raise ValueError("invalid_attribution")
        if utc_status(valid_at) == "UNAVAILABLE":
            raise ValueError("stale_or_future")
        with self._lock:
            if self._closed:
                raise FrameCacheError("runtime_closed")
            frame = self.cache.admit(source_path=source_path, product=product,
                                     valid_at=valid_at, expected_sha256=digest)
            stamp = frame.valid_at.strftime("%Y%m%dT%H%M%SZ")
            reg = TileRegistration(frame=frame, unit=UNITS[product],
                                   palette=palette, palette_verified=palette_verified,
                                   attribution=attribution, quality_verified=quality_verified,
                                   raster_metadata_verified=raster_metadata_verified)
            return PreparedCycle(product, reg, stamp, frame.digest)

    def promote(self, candidate: PreparedCycle):
        with self._lock:
            if self._closed:
                raise FrameCacheError("runtime_closed")
            if utc_status(candidate.registration.frame.valid_at) == "UNAVAILABLE":
                raise ValueError("stale_or_future")
            # Reject a source evicted between staging and publication.
            frame = candidate.registration.frame
            if self.cache.get(product=frame.product, valid_at=frame.valid_at,
                              digest=frame.digest) is not frame:
                raise FrameCacheError("staged_frame_evicted")
            existing = self.registry.active(candidate.product)
            if existing is not None:
                if candidate.stamp < existing.stamp:
                    raise ValueError("older_cycle")
                if candidate.stamp == existing.stamp:
                    if candidate.digest != existing.digest:
                        raise ValueError("conflicting_cycle")
                    return existing.stamp
            # Durably commit the verified bytes before switching the live pointer.
            # Recovery is metadata-only and is never a scientific/HTTP approval.
            if self.journal is not None:
                try:
                    self.journal.commit(frame, candidate.registration.attribution)
                except (OSError, CycleStoreError) as exc:
                    self.last_error = "journal_commit_failed"
                    raise CycleStoreError("journal_commit_failed") from exc
            stamp = self.registry.promote(candidate)
            self.last_promotion_utc = datetime.now(timezone.utc)
            return stamp

    def lookup(self, product, stamp):
        # No production tile exposure before explicit provider and scientific release.
        if not self.enabled or self.services.get(product) is not True:
            return None
        candidate = self.registry.active(product)
        if candidate is None or candidate.stamp != stamp:
            return None
        if utc_status(candidate.registration.frame.valid_at) == "UNAVAILABLE":
            return None
        return self.registry.lookup(product, stamp)

    def close(self):
        with self._lock:
            self._closed = True
            self.enabled = False
            self.services = {product: False for product in PRODUCTS}
            self.registry.revoke()
            self.cache.close(defer=True)
            self._closed = True

    def status(self, *, now=None):
        """Sanitized live operational diagnostics; never exposes source paths."""
        now = datetime.now(timezone.utc) if now is None else now
        with self._lock:
            cycles = {}
            for product in PRODUCTS:
                current = self.registry.active(product)
                valid = current.registration.frame.valid_at if current is not None else None
                age = (now - valid).total_seconds() if valid is not None else None
                cycles[product] = {
                    "service_enabled": self.services.get(product) is True,
                    "generation": current.stamp if current else None,
                    "utc_measurement": valid.isoformat() if valid else None,
                    "age_seconds": round(age, 1) if age is not None else None,
                    "status": utc_status(valid, now=now),
                }
            with self.cache._lock:
                count = len(self.cache._frames)
                bytes_used = sum(frame.byte_size for frame in self.cache._frames.values())
                readers = sum(self.cache._leases.values())
            return {
                "provider_enabled": self.enabled is True, "closed": self._closed,
                "products": cycles, "cached_frames": count,
                "cached_bytes": bytes_used, "active_readers": readers,
                "last_promotion_utc": self.last_promotion_utc.isoformat() if self.last_promotion_utc else None,
                "last_error": self.last_error,
                "http_enabled": False, "consumer_v2_approved": False,
            }
