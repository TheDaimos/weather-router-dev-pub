"""Trusted local OPERA-RATE frame staging for DEV diagnostic tiles.

No browser, websocket or configuration request can supply source paths or grant
scientific approval. The provider/integration calls stage_local_rate only from
a trusted executor with an authorized local HDF5 source.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256
from threading import RLock

from .opera_frame_cache import ImmutableFrameCache
from .opera_odim_metadata import inspect_odim_hdf5
from .opera_rate_registry import RateTileRegistry
from .opera_v2_admission import RateAdmission
from .opera_tile_http import OdimRateTileRegistration


class RateDelivery:
    def __init__(self, *, max_age_seconds=lambda: 1500):
        self.max_age_seconds = max_age_seconds
        self.registry = RateTileRegistry()
        self.cache = ImmutableFrameCache(max_bytes=36 * 1024 * 1024,
                                         protected_paths=self.registry.retained_paths)
        self.current_stamp = None
        self._promotion_lock = RLock()

    def stage_local_rate(self, *, trusted_path: Path, expected_sha256: str,
                         diagnostic_grid, attribution: str) -> str:
        with self._promotion_lock:
            return self._stage_rate_locked(trusted_path=trusted_path, expected_sha256=expected_sha256,
                                           diagnostic_grid=diagnostic_grid, attribution=attribution)

    def _stage_rate_locked(self, *, trusted_path: Path, expected_sha256: str,
                           diagnostic_grid, attribution: str) -> str:
        """Inspect and snapshot an authorized original, without scientific release.

        diagnostic_grid carries a clearly provisional northern-row hypothesis.
        No scientist-supplied pixel evidence is fabricated or promoted.
        """
        from .opera_runtime_dependencies import inspect_rate_runtime
        if inspect_rate_runtime()["runtime_importable"] is not True:
            raise ValueError("native_rate_runtime_unavailable")
        path = Path(trusted_path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 12*1024*1024:
            raise ValueError("untrusted_source")
        if (not isinstance(expected_sha256,str) or len(expected_sha256)!=64
                or any(ch not in "0123456789abcdef" for ch in expected_sha256)):
            raise ValueError("invalid_digest")
        h = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                h.update(chunk)
        if h.hexdigest() != expected_sha256:
            raise ValueError("source_digest_mismatch")
        metadata = inspect_odim_hdf5(path, expected_product="RATE")
        if (getattr(diagnostic_grid,"width",None) != metadata.width
                or getattr(diagnostic_grid,"height",None) != metadata.height
                or getattr(diagnostic_grid,"row_zero_north",None) is not True):
            raise ValueError("unverified_diagnostic_grid")
        stamp_time = datetime.fromisoformat(metadata.valid_at.replace("Z","+00:00"))
        # Frame lifetime comes from the current persisted WR user policy.
        age = (datetime.now(timezone.utc)-stamp_time).total_seconds()
        if not 0 <= age <= self.max_age_seconds():
            raise ValueError("stale_or_future_source")
        candidate_stamp = stamp_time.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if self.current_stamp is not None and candidate_stamp <= self.current_stamp:
            current = self.registry.lookup("RATE", self.current_stamp)
            if (candidate_stamp == self.current_stamp and current is not None
                    and current.frame.digest == expected_sha256):
                return self.current_stamp
            raise ValueError("non_monotonic_radar_cycle")
        frame = self.cache.admit(source_path=path, product="RATE",
                                 valid_at=stamp_time, expected_sha256=expected_sha256)
        registration = OdimRateTileRegistration(
            frame=frame, unit="mm/h", palette=lambda _: (0,0,0,0),
            palette_verified=False, attribution=attribution,
            quality_verified=False, raster_metadata_verified=True,
            grid=diagnostic_grid, projection=metadata.projection,
            dataset_path=metadata.dataset_path,
            row_orientation_verified=False, original_pixel_positions_verified=False,
            geographic_corners=metadata.geographic_corners)
        stamp = self.registry.register_diagnostic(registration)
        self.current_stamp = stamp
        return stamp

    def admit_verified_current(self, *, admission: RateAdmission,
                               verified_registration: OdimRateTileRegistration) -> str:
        """Accept an externally verified registration for this exact frame.

        The caller must supply independently established scientific flags,
        native runtime verification and a verified palette. This method never
        invents or elevates any evidence bit.
        """
        with self._promotion_lock:
            stamp = self.current_stamp
            existing = self.registry.lookup("RATE", stamp) if stamp else None
            if (not isinstance(admission, RateAdmission) or not admission.ready
                    or not isinstance(verified_registration, OdimRateTileRegistration)
                    or existing is None or stamp is None
                    or admission.valid_at != existing.frame.valid_at
                    or verified_registration.frame != existing.frame
                    or verified_registration.frame.digest != existing.frame.digest
                    or not callable(verified_registration.palette)
                    or not all((
                        verified_registration.palette_verified is True,
                        verified_registration.quality_verified is True,
                        verified_registration.raster_metadata_verified is True,
                        verified_registration.row_orientation_verified is True,
                        verified_registration.original_pixel_positions_verified is True,
                    ))):
                raise ValueError("trusted_rate_admission_required")
            from .opera_runtime_dependencies import inspect_rate_runtime
            if inspect_rate_runtime()["runtime_importable"] is not True:
                raise ValueError("native_rate_runtime_unavailable")
            # The observation map and raster become current atomically. A failed
            # map cannot replace the previous complete admitted generation.
            from dataclasses import replace
            from .opera_observation_coverage import build_observation_coverage
            try:
                mask = build_observation_coverage(verified_registration)
            except Exception as err:
                raise ValueError("observation_mask_unavailable") from err
            verified_registration = replace(verified_registration, observation_mask=mask)
            result = self.registry.register(verified_registration, admission)
            if result != stamp:
                raise ValueError("admission_stamp_mismatch")
            return result

    def revoke(self):
        with self._promotion_lock:
            self.registry.revoke()
            self.current_stamp = None

    def reset(self):
        """Prevent staging from racing with cache teardown and registry reset."""
        with self._promotion_lock:
            self.revoke()
            self.cache.close()
            self.cache = ImmutableFrameCache(max_bytes=36 * 1024 * 1024,
                                             protected_paths=self.registry.retained_paths)

    def close(self):
        with self._promotion_lock:
            self.revoke()
            self.cache.close()
