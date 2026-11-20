"""Trusted ring-buffer -> existing RATE delivery bridge (diagnostic only).

Never accepts browser paths or scientific approval claims. All methods are
blocking and must be invoked in Home Assistant's executor, not its event loop.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from .opera_odim_metadata import inspect_odim_hdf5
from .opera_odim_reconstruction import reconstruct_laea


class RingRateBridge:
    def __init__(self, *, ring, delivery, age_limit, trusted_admission=None):
        self.ring = ring
        self.delivery = delivery
        self.age_limit = age_limit
        self.trusted_admission = trusted_admission
        self.last_error = None
        self.last_stamp = None

    def stage_latest(self, *, allowed: bool) -> dict:
        if allowed is not True:
            return {"status": "provider_or_rate_disabled", "scientific_status": "UNVERIFIED"}
        # Ring catalog verifies the owned HDF5 magic, size and SHA-256.
        # Never accept a path or checksum from the API caller.
        entries = sorted(self.ring.verified_frame_catalog(),
                         key=lambda row: row["stamp"], reverse=True)
        for entry in entries:
            stamp = entry["stamp"]
            measured = datetime.fromisoformat(entry["valid_at"].replace("Z", "+00:00"))
            if not 0 <= (datetime.now(timezone.utc) - measured).total_seconds() <= self.age_limit():
                continue
            try:
                with self.ring.read_frame(stamp) as path:
                    checksum = sha256()
                    with path.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(65536), b""):
                            checksum.update(chunk)
                    if checksum.hexdigest() != entry["sha256"]:
                        raise ValueError("ring_frame_digest_mismatch")
                    metadata = inspect_odim_hdf5(path, expected_product="RATE")
                    if datetime.fromisoformat(metadata.valid_at.replace("Z", "+00:00")) != measured:
                        raise ValueError("odim_time_mismatch")
                    if not metadata.geographic_corners or not metadata.pixel_scale:
                        raise ValueError("odim_grid_metadata_missing")
                    # Northern storage row is an explicit, unverified diagnostic
                    # hypothesis. Production orientation/pixel gates remain CLOSED.
                    grid = reconstruct_laea(
                        projection=metadata.projection, corners=metadata.geographic_corners,
                        width=metadata.width, height=metadata.height,
                        xscale=metadata.pixel_scale[0], yscale=metadata.pixel_scale[1],
                        row_zero_north=True)
                    registered = self.delivery.stage_local_rate(
                        trusted_path=path, expected_sha256=checksum.hexdigest(),
                        diagnostic_grid=grid, attribution="EUMETNET OPERA RATE (unverified DEV diagnostic)")
                if self.trusted_admission is not None:
                    current = self.delivery.registry.lookup("RATE", registered)
                    proof = self.trusted_admission(current)
                    if proof is not None:
                        admission, verified_registration = proof
                        active = self.delivery.admit_verified_current(
                            admission=admission,
                            verified_registration=verified_registration)
                        self.last_stamp, self.last_error = active, None
                        return {"status": "registered_approved", "stamp": active,
                                "scientific_status": "ADMITTED", "tile_authorized": True}
                self.last_stamp, self.last_error = registered, None
                return {"status": "registered_diagnostic", "stamp": registered,
                        "scientific_status": "UNVERIFIED", "tile_authorized": False}
            except (OSError, ValueError, ImportError) as exc:
                # Do not leak local paths, native exception contents or data.
                self.last_error = type(exc).__name__ if type(exc).__name__ in (
                    "OdimMetadataError", "OperaReconstructionError", "FrameCacheError") else (
                    str(exc) if type(exc) is ValueError and str(exc) in (
                        "ring_frame_digest_mismatch", "odim_time_mismatch",
                        "odim_grid_metadata_missing", "native_rate_runtime_unavailable", "observation_mask_unavailable",
                        "stale_or_future_source", "non_monotonic_radar_cycle",
                        "unverified_diagnostic_grid") else "rate_stage_failed")
                if self.last_error == "non_monotonic_radar_cycle":
                    return {"status": "no_newer_generation", "stamp": self.delivery.current_stamp,
                            "scientific_status": "UNVERIFIED"}
                continue
        return {"status": "no_eligible_rate_generation", "last_error": self.last_error,
                "scientific_status": "UNVERIFIED"}
