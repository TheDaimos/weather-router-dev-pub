"""Admin-only, pinned original OPERA RATE north/south diagnostic comparison.

Not a live tile route, not Consumer V2 and never a scientific approval.
All work must run in the HA executor; the owned ring lock pins the original.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from .opera_ring_buffer import _utc
from .opera_odim_metadata import inspect_odim_hdf5
from .opera_odim_reconstruction import reconstruct_laea
from .opera_preview_tile import render_preview

ALLOWED_HYPOTHESES = ("north_first", "south_first")


def compare_ring_frame(*, ring, stamp: str, z: int, x: int, y: int) -> dict:
    """Both images are produced under one owned-ring read lease."""
    _utc(stamp)
    if any(type(v) is not int for v in (z, x, y)) or not 0 <= z <= 12 or not 0 <= x < (1 << z) or not 0 <= y < (1 << z):
        raise ValueError("invalid_tile_coordinates")
    catalog = ring.verified_frame_catalog()
    record = next((row for row in catalog if row["stamp"] == stamp), None)
    if record is None:
        raise ValueError("frame_not_found")
    with ring.read_frame(stamp) as source:
        path = Path(source)
        digest = sha256()
        with path.open("rb") as stream:
            for part in iter(lambda: stream.read(65536), b""):
                digest.update(part)
        value = digest.hexdigest()
        if value != record["sha256"]:
            raise ValueError("frame_integrity_failed")
        metadata = inspect_odim_hdf5(path, expected_product="RATE")
        measured = datetime.fromisoformat(metadata.valid_at.replace("Z", "+00:00"))
        if measured.astimezone(timezone.utc) != _utc(stamp):
            raise ValueError("odim_time_mismatch")
        if not metadata.geographic_corners or not metadata.pixel_scale:
            raise ValueError("georeference_missing")
        grid = reconstruct_laea(
            projection=metadata.projection, corners=metadata.geographic_corners,
            width=metadata.width, height=metadata.height,
            xscale=metadata.pixel_scale[0], yscale=metadata.pixel_scale[1],
            row_zero_north=True)
        import base64
        result = {}
        for hypothesis in ALLOWED_HYPOTHESES:
            png, statistics = render_preview(path, digest=value, grid=grid,
                                 projection=metadata.projection,
                                 dataset_path=metadata.dataset_path,
                                 z=z, x=x, y=y, hypothesis=hypothesis,
                                 include_statistics=True)
            result[hypothesis] = {"png_base64": base64.b64encode(png).decode("ascii"),
                                  "png_bytes": len(png), "pixel_statistics": statistics,
                                  "status": "rendered_unverified"}
    return {"schema": "weather_router.opera.test68_d.historical.v1",
            "test_id": "TEST68-D", "mode": "historical_diagnostic",
            "selected_observation_utc": measured.isoformat().replace("+00:00", "Z"),
            "selected_frame_sha256": value, "selected_frame_identifier": stamp,
            "z": z, "x": x, "y": y, "north_first": result["north_first"],
            "south_first": result["south_first"], "scientific_approval": False,
            "consumer_v2_authorized": False, "weather_warnings_authorized": False}


def compare_pinned_original(*, original: bytes, stamp: str, expected_sha256: str,
                            z: int, x: int, y: int) -> dict:
    """Render pinned owned bytes only, independently of later monitor eviction.

    The private copy is bounded to one HDF5 original and is erased immediately
    after both diagnostic variants finish; no live registry or cache writes.
    """
    import tempfile
    from contextlib import contextmanager
    if type(original) is not bytes or not 8 <= len(original) <= 12 * 1024 * 1024:
        raise ValueError("frame_size_invalid")
    if not original.startswith(bytes((0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a))):
        raise ValueError("frame_hdf5_magic_invalid")
    if sha256(original).hexdigest() != expected_sha256:
        raise ValueError("frame_integrity_failed")
    with tempfile.TemporaryDirectory(prefix="weather-router-test68-") as directory:
        path = Path(directory) / "pinned-original.h5"
        with path.open("xb") as handle:
            path.chmod(0o600)
            handle.write(original)
        class PinnedRing:
            def verified_frame_catalog(self):
                return [{"stamp": stamp, "sha256": expected_sha256}]
            @contextmanager
            def read_frame(self, requested_stamp):
                if requested_stamp != stamp:
                    raise ValueError("frame_not_found")
                yield path
        return compare_ring_frame(ring=PinnedRing(), stamp=stamp,
                                  z=z, x=x, y=y)
