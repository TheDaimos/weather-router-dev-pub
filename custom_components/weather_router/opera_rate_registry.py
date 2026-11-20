"""Server-owned, bounded OPERA RATE tile registry for the existing HTTP view.

Scientific admission must be provided by trusted server code, never by a
Consumer V2 request, URL parameter or provider-returned untrusted field.
"""
from __future__ import annotations
from datetime import datetime, timezone
from threading import RLock

from .opera_tile_http import OdimRateTileRegistration
from .opera_frame_cache import VerifiedFrame
from .opera_v2_admission import RateAdmission


class RateRegistryError(ValueError):
    pass


class RateTileRegistry:
    def __init__(self):
        self._lock = RLock()
        self._item = None
        self._diagnostic = False
        self._pending = None
        self._previous = None

    def register(self, registration: OdimRateTileRegistration, admission: RateAdmission):
        if not isinstance(registration, OdimRateTileRegistration) or not isinstance(admission, RateAdmission):
            raise RateRegistryError("untrusted_registration")
        frame = registration.frame
        if not isinstance(frame, VerifiedFrame) or frame.product != "RATE":
            raise RateRegistryError("invalid_rate_frame")
        if not admission.ready or admission.valid_at != frame.valid_at or not registration.row_orientation_verified or not registration.original_pixel_positions_verified:
            raise RateRegistryError("scientific_gate_closed")
        if not all((registration.quality_verified is True, registration.raster_metadata_verified is True,
                    registration.palette_verified is True, registration.unit == "mm/h",
                    registration.grid is not None, bool(registration.projection),
                    bool(registration.dataset_path), bool(registration.attribution.strip()))):
            raise RateRegistryError("frame_metadata_unapproved")
        stamp = frame.valid_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        with self._lock:
            if self._item is not None and stamp < self._item[0]:
                raise RateRegistryError("older_approved_generation")
            if self._item is not None and stamp != self._item[0]:
                self._previous = self._item
            self._item = (stamp, registration, admission)
            self._pending = None
            self._diagnostic = False
        return stamp

    def register_diagnostic(self, registration: OdimRateTileRegistration):
        """Unapproved scientific pixels: explicitly labelled DEV-only registration.

        The caller must already have verified ODIM metadata and source provenance.
        The server must independently enforce administrator-only diagnostic access.
        """
        if not isinstance(registration, OdimRateTileRegistration):
            raise RateRegistryError("untrusted_registration")
        frame = registration.frame
        if not isinstance(frame, VerifiedFrame) or frame.product != "RATE":
            raise RateRegistryError("invalid_rate_frame")
        if (registration.unit != "mm/h" or registration.grid is None
                or not registration.projection or not registration.dataset_path
                or not registration.attribution.strip()
                or registration.raster_metadata_verified is not True):
            raise RateRegistryError("invalid_diagnostic_metadata")
        stamp = frame.valid_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        with self._lock:
            if self._item is not None and stamp <= self._item[0]:
                raise RateRegistryError("older_diagnostic_generation")
            self._pending = (stamp, registration, None)
            self._diagnostic = True
        return stamp

    def is_diagnostic(self, product: str, stamp: str) -> bool:
        with self._lock:
            return bool(self._diagnostic and product == "RATE" and self._pending
                        and self._pending[0] == stamp)

    def lookup(self, product: str, stamp: str):
        with self._lock:
            if product != "RATE":
                return None
            for item in (self._item, self._previous, self._pending):
                if item is not None and item[0] == stamp:
                    return item[1]
            return None

    def admitted(self, product: str, stamp: str):
        with self._lock:
            if product == "RATE":
                for item in (self._item, self._previous):
                    if item is not None and item[0] == stamp:
                        return item[2]
            return None

    def current_approved_stamp(self):
        with self._lock:
            return self._item[0] if self._item is not None else None

    def delivery_state(self, *, enabled: bool, max_age_seconds: int, now=None):
        with self._lock:
            item = self._item
            ready = bool(item is not None and isinstance(item[2], RateAdmission)
                         and item[2].ready and item[2].valid_at == item[1].frame.valid_at)
            instant = now or datetime.now(timezone.utc)
            age = ((instant - item[1].frame.valid_at).total_seconds()
                   if ready and instant.tzinfo is not None else None)
            available = bool(ready and enabled is True and type(max_age_seconds) is int
                             and 1 <= max_age_seconds <= 3600 and age is not None
                             and 0 <= age <= max_age_seconds)
            return {"approved_rate_stamp": item[0] if ready else None,
                    "scientific_scope": "RATE_visualization_only",
                    "scientific_tile_approved": ready,
                    "scientific_status": "TEST69_RATE_VALIDATED" if ready else "NO_ADMITTED_RATE_FRAME",
                    "production_tiles_authorized": available,
                    "diagnostic_registration_only": not ready,
                    "age_seconds": age}

    def retained_paths(self):
        with self._lock:
            return {item[1].frame.path for item in (self._item, self._previous) if item is not None}

    def revoke(self):
        with self._lock:
            self._item = None
            self._previous = None
            self._pending = None
            self._diagnostic = False
