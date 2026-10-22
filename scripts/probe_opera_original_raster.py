"""Offline, read-only F7 forensic check of immutable OPERA GeoTIFF references.

Do not install in HA or activate providers. Run only on an approved, isolated
machine with rasterio/numpy and a locally obtained OPERA source file.
File contents, pixels, paths, native errors and user locations never appear
in JSON. Matching a checksum does NOT validate quality1, palettes or an HA
installation; the product gate remains BLOCKED unconditionally.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import tempfile

MAX_BYTES = 12 * 1024 * 1024
ORIGINALS = {
    "CIRRUS_DBZH_20261019T1340": (
        "DBZH", "817b99bd945d557f8a59c4e9b458d1ea230fa2d720383dcdd95c41cbafdb9d28"),
    "NIMBUS_RATE_20261019T1315": (
        "RATE", "b4321b6d4b2ad8165da495165ad6e46af9d6e843d0fbbe22b6d6b57af05d05d5"),
}
SCHEMA = "weather_router.opera.original_raster_forensic.v1"

# Fixed historical references, never derive the nominal source time from S3
# retrieval timestamps, file mtimes, or the native TIFF metadata itself.
REFERENCE_TIME = {
    "CIRRUS_DBZH_20261019T1340": ("DBZH", "20261019", "134000"),
    "NIMBUS_RATE_20261019T1315": ("RATE", "20261019", "131500"),
}


def _classified_metadata(ds, *, product, reference):
    """Classify only allowlisted technical TIFF attributes, never copy raw tags.

    Matching tags are a provenance consistency check, NOT confirmation of a
    scientific quality mask or of the live 900-second UTC freshness policy.
    """
    tags = ds.tags()
    expected = REFERENCE_TIME.get(reference)
    if expected is None:
        nominal = "not_checked"
    elif (tags.get("date") is None or tags.get("time") is None):
        nominal = "not_available"
    elif tags.get("date") == expected[1] and tags.get("time") == expected[2]:
        nominal = "matches_reference"
    else:
        nominal = "mismatch"

    first = ds.descriptions[0] if ds.descriptions else None
    second = ds.descriptions[1] if len(ds.descriptions) > 1 else None
    try:
        quality_task_known = (ds.tags(2).get("task") ==
                              "pl.imgw.quality.qi_total")
    except Exception:
        quality_task_known = False
    return {
        "nominal_time_consistency": nominal,
        "nominal_time_basis": "fixed_reference_utc_not_retrieval_time",
        "band1_label_matches_product": first == product,
        "band2_label_is_quality1": second == "quality1",
        "known_qi_total_task_label_present": quality_task_known,
        "cog_layout_marker_present": (
            ds.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") == "COG"),
        "quality1_scientific_policy": "unverified",
        "nominal_freshness_for_live_response": "not_tested",
    }


class OriginalRasterProbeError(ValueError):
    """Only a fixed, non-sensitive reason may be externally reported."""


@contextmanager
def _verified_private_snapshot(source_path, expected_sha256):
    """Hash the *same private bytes* later read by GDAL, never trust a mutable source.

    Source is opened read-only with O_NOFOLLOW; writes occur only to an
    unpredictable 0700 temporary staging directory, removed after inspection.
    This is not the production ImmutableFrameCache and never enables HA.
    """
    source = Path(source_path)
    if source.is_symlink():
        raise OriginalRasterProbeError("invalid_local_source")
    fd = None
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OriginalRasterProbeError("invalid_local_source")
        if not 0 < info.st_size <= MAX_BYTES:
            raise OriginalRasterProbeError("invalid_source_size")
    except (OSError, OriginalRasterProbeError) as exc:
        # A rejected regularity/size check happens *before* the snapshot
        # context's finally block. Close the already opened source here.
        if fd is not None:
            os.close(fd)
            fd = None
        if isinstance(exc, OriginalRasterProbeError):
            raise
        raise OriginalRasterProbeError("invalid_local_source") from None
    try:
        with tempfile.TemporaryDirectory(prefix="wr-opera-forensic-") as folder:
            local = Path(folder) / "verified-original.tiff"
            digest = sha256()
            size = 0
            with os.fdopen(fd, "rb") as incoming:
                fd = None
                # Exclusive new destination, only owner-readable; no caller
                # input is ever used as a destination pathname.
                out_fd = os.open(local, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(out_fd, "wb") as out:
                    while block := incoming.read(65536):
                        size += len(block)
                        if size > MAX_BYTES:
                            raise OriginalRasterProbeError("invalid_source_size")
                        digest.update(block)
                        out.write(block)
            if size != info.st_size or digest.hexdigest() != expected_sha256:
                raise OriginalRasterProbeError("sha256_mismatch")
            yield local, size, digest.hexdigest()
    except OriginalRasterProbeError:
        raise
    except OSError:
        raise OriginalRasterProbeError("invalid_local_source") from None
    finally:
        if fd is not None:
            os.close(fd)


def inspect_file(source_path, *, product, expected_sha256, reference=None):
    """Count raster value classes in bounded windows; never infer quality1."""
    if product not in ("DBZH", "RATE") or not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ):
        raise OriginalRasterProbeError("invalid_expected_identity")
    if reference is not None:
        # A named historical original is inseparable from its fixed SHA-256.
        # Do not allow a caller to relabel arbitrary bytes as that reference.
        if (type(reference) is not str
                or REFERENCE_TIME.get(reference, (None,))[0] != product
                or ORIGINALS.get(reference) != (product, expected_sha256)):
            raise OriginalRasterProbeError("invalid_expected_identity")
    with _verified_private_snapshot(source_path, expected_sha256) as (snapshot, nbytes, digest):
        return _inspect_verified_snapshot(snapshot, product=product,
                                          nbytes=nbytes, digest=digest,
                                          reference=reference)


def _inspect_verified_snapshot(src_path, *, product, nbytes, digest,
                               reference=None):
    """Raster scan uses private SHA-verified bytes, never the mutable input."""
    try:
        import numpy as np
        import rasterio
        from rasterio.windows import Window
        with rasterio.Env(GDAL_CACHEMAX=8, GDAL_NUM_THREADS="1"):
            with rasterio.open(src_path) as ds:
                if (ds.driver != "GTiff" or ds.crs is None or ds.count < 2 or
                    ds.width <= 0 or ds.height <= 0 or
                    ds.width * ds.height > 50_000_000):
                    raise OriginalRasterProbeError("invalid_geotiff_geometry")
                if ds.transform.is_degenerate:
                    raise OriginalRasterProbeError("invalid_geotiff_geometry")
                nodata = ds.nodata
                stats = {name: 0 for name in (
                    "total", "nan", "infinite", "sentinel", "valid_negative", "valid_zero",
                    "valid_positive", "quality_nonfinite_on_valid", "quality_zero_on_valid",
                    "quality_positive_on_valid", "quality_negative_on_valid",
                )}
                for top in range(0, ds.height, 512):
                    for left in range(0, ds.width, 512):
                        window = Window(left, top, min(512, ds.width-left),
                                        min(512, ds.height-top))
                        pixels = ds.read(1, window=window, out_dtype="float32")
                        quality = ds.read(2, window=window, out_dtype="float32")
                        finite = np.isfinite(pixels)
                        sentinel = finite & (pixels == -9999000)
                        if nodata is not None and np.isfinite(nodata):
                            sentinel |= finite & (pixels == nodata)
                        valid = finite & ~sentinel
                        stats["total"] += int(pixels.size)
                        stats["nan"] += int(np.count_nonzero(np.isnan(pixels)))
                        stats["infinite"] += int(np.count_nonzero(np.isinf(pixels)))
                        stats["sentinel"] += int(np.count_nonzero(sentinel))
                        stats["valid_negative"] += int(np.count_nonzero(valid & (pixels < 0)))
                        stats["valid_zero"] += int(np.count_nonzero(valid & (pixels == 0)))
                        stats["valid_positive"] += int(np.count_nonzero(valid & (pixels > 0)))
                        stats["quality_nonfinite_on_valid"] += int(np.count_nonzero(valid & ~np.isfinite(quality)))
                        stats["quality_zero_on_valid"] += int(np.count_nonzero(valid & np.isfinite(quality) & (quality == 0)))
                        stats["quality_positive_on_valid"] += int(np.count_nonzero(valid & np.isfinite(quality) & (quality > 0)))
                        stats["quality_negative_on_valid"] += int(np.count_nonzero(valid & np.isfinite(quality) & (quality < 0)))
                if stats["nan"] + stats["infinite"] + stats["sentinel"] + sum(
                    stats[k] for k in ("valid_negative", "valid_zero", "valid_positive")
                ) != stats["total"]:
                    raise OriginalRasterProbeError("invalid_pixel_partition")
                return {
                    "schema": SCHEMA, "product": product,
                    "expected_reference_matched": True,
                    "sha256": digest, "source_size_bytes": nbytes,
                    "width": ds.width, "height": ds.height,
                    "bands": ds.count, "unit": "dBZ" if product == "DBZH" else "mm/h",
                    "technical_metadata": _classified_metadata(
                        ds, product=product, reference=reference),
                    "pixel_counts": stats,
                    "quality1_scientific_meaning": "unverified",
                    "color_palette": "unverified", "ha_installation": "BLOCKED",
                    "consumer_provider_activation": "BLOCKED",
                    "ha_real_acceptance": "NOT_TESTED",
                }
    except OriginalRasterProbeError:
        raise
    except Exception:
        # Do not propagate paths or GDAL native messages to exported JSON.
        raise OriginalRasterProbeError("raster_inspection_failed") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only OPERA original checksum/pixel audit")
    parser.add_argument("--reference", choices=sorted(ORIGINALS), required=True)
    parser.add_argument("--source", required=True, help="Locally provided immutable TIFF; never exported")
    args = parser.parse_args(argv)
    product, digest = ORIGINALS[args.reference]
    try:
        result = inspect_file(args.source, product=product,
                              expected_sha256=digest, reference=args.reference)
    except OriginalRasterProbeError as exc:
        result = {"schema": SCHEMA, "reference": args.reference,
                  "status": str(exc), "ha_installation": "BLOCKED",
                  "consumer_provider_activation": "BLOCKED",
                  "ha_real_acceptance": "NOT_TESTED"}
    else:
        result["reference"] = args.reference
        result["status"] = "source_hash_and_raw_pixel_classes_verified_only"
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "source_hash_and_raw_pixel_classes_verified_only" else 1


if __name__ == "__main__":
    raise SystemExit(main())
