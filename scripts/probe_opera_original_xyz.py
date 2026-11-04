"""F7 read-only XYZ pixel coverage probe for a hash-verified OPERA original.

Run ONLY on an approved isolated test machine with the actual historic GeoTIFF
file present. This deliberately calls the EXISTING F13 CoG renderer; black
opaque means merely 'a finite measurement exists', not a weather colour.
No saved PNG, no HA imports, no network, no provider registration.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from io import BytesIO
import importlib.util
import json
from pathlib import Path

from probe_opera_original_raster import (
    ORIGINALS, REFERENCE_TIME, OriginalRasterProbeError,
    _inspect_verified_snapshot, _verified_private_snapshot,
)

SCHEMA = "weather_router.opera.original_xyz_mask_diagnostic.v1"


class OriginalXYZProbeError(ValueError):
    """Only allowlisted failure status, never raw native exception text."""


def _load_existing_f13_renderer():
    # Standalone direct module load deliberately avoids importing HA integration
    # entrypoints and does not register HTTP routes.
    path = Path(__file__).resolve().parents[1] / (
        "custom_components/weather_router/opera_cog_tiles.py")
    spec = importlib.util.spec_from_file_location(
        "_wr_f7_original_xyz_existing_renderer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspect_original_xyz(source, *, reference, z, x, y):
    """Return ONLY classified 256x256 alpha coverage for one trusted source."""
    if type(reference) is not str or reference not in ORIGINALS:
        raise OriginalXYZProbeError("invalid_reference")
    if any(type(v) is not int for v in (z, x, y)):
        raise OriginalXYZProbeError("invalid_xyz")
    if not 0 <= z <= 16 or not 0 <= x < (1 << z) or not 0 <= y < (1 << z):
        raise OriginalXYZProbeError("invalid_xyz")

    product, expected_sha = ORIGINALS[reference]
    expected_product, date, clock = REFERENCE_TIME[reference]
    if product != expected_product:
        raise OriginalXYZProbeError("invalid_reference")
    # Source time exclusively from the already verified historic identity.
    nominal = datetime.strptime(date + clock, "%Y%m%d%H%M%S").replace(
        tzinfo=timezone.utc)
    try:
        with _verified_private_snapshot(source, expected_sha) as (
            snapshot, nbytes, digest
        ):
            evidence = _inspect_verified_snapshot(
                snapshot, product=product, nbytes=nbytes,
                digest=digest, reference=reference)
            meta = evidence["technical_metadata"]
            if (meta["nominal_time_consistency"] != "matches_reference"
                    or meta["band1_label_matches_product"] is not True):
                raise OriginalXYZProbeError("source_metadata_not_confirmed")

            # A SECOND digest check is performed by the existing F13 renderer,
            # on the same private immutable snapshot used for statistics.
            renderer = _load_existing_f13_renderer()
            renderer.immutable_key(
                product=product, source_time=nominal, source_sha256=digest,
                z=z, x=x, y=y, palette_rev="diagonly",
                quality_rev="unverified")
            png = renderer.render_verified_cog(
                trusted_path=snapshot, expected_sha256=digest,
                z=z, x=x, y=y, verified_frame=None,
                palette=lambda value: (0, 0, 0, 255))
            # No PNG or pixel array is written/exported. Decode in RAM and
            # report aggregate alpha counts only. Black is NOT a weather palette.
            from PIL import Image
            import numpy as np
            with Image.open(BytesIO(png)) as im:
                if im.format != "PNG" or im.size != (256, 256):
                    raise OriginalXYZProbeError("invalid_render_output")
                alpha = np.asarray(im.convert("RGBA"), dtype=np.uint8)[:, :, 3]
                opaque = int(np.count_nonzero(alpha))
                if np.count_nonzero((alpha != 0) & (alpha != 255)):
                    raise OriginalXYZProbeError("invalid_render_output")
            return {
                "schema": SCHEMA,
                "reference": reference, "product": product,
                "unit": evidence["unit"], "sha256": digest,
                "source_identity": "sha256_and_utc_metadata_confirmed",
                "z": z, "x": x, "y": y,
                "xyz_total_pixels": 65536,
                "xyz_opaque_measurement_pixels": opaque,
                "xyz_transparent_pixels": 65536 - opaque,
                "renderer": "existing_f13_cog_to_xyz",
                "diagnostic_palette": "opaque_black_only_not_scientific",
                "quality1_scientific_meaning": "unverified",
                "color_palette": "unverified",
                "ha_installation": "BLOCKED",
                "consumer_provider_activation": "BLOCKED",
                "ha_real_acceptance": "NOT_TESTED",
            }
    except (OriginalXYZProbeError, OriginalRasterProbeError):
        raise
    except Exception:
        raise OriginalXYZProbeError("diagnostic_render_failed") from None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Offline OPERA hash-bound existing-F13 XYZ mask probe")
    parser.add_argument("--reference", choices=sorted(ORIGINALS), required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--z", type=int, required=True)
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect_original_xyz(
            args.source, reference=args.reference, z=args.z, x=args.x, y=args.y)
    except (OriginalRasterProbeError, OriginalXYZProbeError) as exc:
        result = {
            "schema": SCHEMA, "reference": args.reference,
            "status": str(exc), "ha_installation": "BLOCKED",
            "consumer_provider_activation": "BLOCKED",
            "ha_real_acceptance": "NOT_TESTED"}
        rc = 1
    else:
        result["status"] = "offline_xyz_mask_only_not_product_approval"
        rc = 0
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
