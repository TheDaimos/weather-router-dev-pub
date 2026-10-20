"""Offline, read-only F7 forensic check of immutable OPERA GeoTIFF references.

Do not install in HA or activate providers. Run only on an approved, isolated
machine with rasterio/numpy and a locally obtained OPERA source file.
File contents, pixels, paths, native errors and user locations never appear
in JSON. Matching a checksum does NOT validate quality1, palettes or an HA
installation; the product gate remains BLOCKED unconditionally.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

MAX_BYTES = 12 * 1024 * 1024
ORIGINALS = {
    "CIRRUS_DBZH_20261019T1340": (
        "DBZH", "817b99bd945d557f8a59c4e9b458d1ea230fa2d720383dcdd95c41cbafdb9d28"),
    "NIMBUS_RATE_20261019T1315": (
        "RATE", "b4321b6d4b2ad8165da495165ad6e46af9d6e843d0fbbe22b6d6b57af05d05d5"),
}
SCHEMA = "weather_router.opera.original_raster_forensic.v1"


class OriginalRasterProbeError(ValueError):
    """Only a fixed, non-sensitive reason may be externally reported."""


def inspect_file(source_path, *, product, expected_sha256):
    """Count raster value classes in bounded windows; never infer quality1."""
    if product not in ("DBZH", "RATE") or not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ):
        raise OriginalRasterProbeError("invalid_expected_identity")
    src_path = Path(source_path)
    if src_path.is_symlink() or not src_path.is_file():
        raise OriginalRasterProbeError("invalid_local_source")
    nbytes = src_path.stat().st_size
    if not 0 < nbytes <= MAX_BYTES:
        raise OriginalRasterProbeError("invalid_source_size")
    digest = sha256()
    with src_path.open("rb") as inp:
        for chunk in iter(lambda: inp.read(65536), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise OriginalRasterProbeError("sha256_mismatch")
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
                    "sha256": digest.hexdigest(), "source_size_bytes": nbytes,
                    "width": ds.width, "height": ds.height,
                    "bands": ds.count, "unit": "dBZ" if product == "DBZH" else "mm/h",
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
        result = inspect_file(args.source, product=product, expected_sha256=digest)
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
