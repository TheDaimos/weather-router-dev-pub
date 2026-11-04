"""F7 isolated original-source XYZ diagnostic; every fixture is SYNTHETIC."""
from __future__ import annotations

from hashlib import sha256
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
xyz = importlib.import_module("probe_opera_original_xyz")


class OriginalXYZMaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = Path(self.tmp.name) / "synthetic_two_band_laea.tiff"
        arr = np.full((256, 256), -9999000, dtype="float32")
        arr[20:210, 25:210] = -8.0
        arr[70:100, 75:100] = 18.0
        arr[110:135, 95:120] = np.nan
        arr[75:80, 80:85] = 0.0
        laea = ("+proj=laea +lat_0=55 +lon_0=10 +x_0=1950000 "
                "+y_0=-2100000 +datum=WGS84 +units=m +no_defs")
        with rasterio.open(
            self.source, "w", driver="GTiff", width=256, height=256,
            count=2, dtype="float32", crs=laea,
            transform=from_origin(1850000, -1850000, 1000, 1000),
            nodata=-9999000, tiled=True, blockxsize=128, blockysize=128,
        ) as ds:
            ds.write(arr, 1)
            ds.write(np.zeros((256, 256), dtype="float32"), 2)
            ds.set_band_description(1, "DBZH")
            ds.set_band_description(2, "quality1")
            ds.update_tags(date="20261019", time="134000")
        self.digest = sha256(self.source.read_bytes()).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def _synthetic_reference(self):
        return patch.dict(xyz.ORIGINALS, {
            "CIRRUS_DBZH_20261019T1340": ("DBZH", self.digest)
        })

    def test_synthetic_laea_true_existing_f13_xyz_and_blank_edge(self):
        with self._synthetic_reference():
            active = xyz.inspect_original_xyz(
                self.source, reference="CIRRUS_DBZH_20261019T1340",
                z=6, x=33, y=19)
            blank = xyz.inspect_original_xyz(
                self.source, reference="CIRRUS_DBZH_20261019T1340",
                z=6, x=33, y=21)
        self.assertEqual(active["renderer"], "existing_f13_cog_to_xyz")
        self.assertEqual(active["source_identity"],
                         "sha256_and_utc_metadata_confirmed")
        self.assertGreater(active["xyz_opaque_measurement_pixels"], 0)
        self.assertGreater(active["xyz_transparent_pixels"], 0)
        self.assertEqual(active["xyz_total_pixels"], 65536)
        self.assertEqual(blank["xyz_opaque_measurement_pixels"], 0)
        self.assertEqual(blank["xyz_transparent_pixels"], 65536)
        self.assertEqual(active["diagnostic_palette"],
                         "opaque_black_only_not_scientific")
        self.assertEqual(active["color_palette"], "unverified")
        self.assertEqual(active["quality1_scientific_meaning"], "unverified")
        self.assertEqual(active["consumer_provider_activation"], "BLOCKED")
        self.assertEqual(active["ha_real_acceptance"], "NOT_TESTED")
        self.assertNotIn(str(self.source), str(active))

    def test_reference_sha_mismatch_rejected_before_existing_f13_render(self):
        # Real reference hash must not validate a synthetic TIFF.
        with patch.object(xyz, "_load_existing_f13_renderer") as renderer:
            with self.assertRaisesRegex(
                    xyz.OriginalRasterProbeError, "^sha256_mismatch$"):
                xyz.inspect_original_xyz(
                    self.source, reference="CIRRUS_DBZH_20261019T1340",
                    z=6, x=33, y=19)
            renderer.assert_not_called()

    def test_mismatched_utc_or_product_label_blocks_xyz(self):
        with rasterio.open(self.source, "r+") as ds:
            ds.update_tags(date="20261019", time="134500",
                           untrusted_path="/private/secret")
        digest = sha256(self.source.read_bytes()).hexdigest()
        with patch.dict(xyz.ORIGINALS, {
            "CIRRUS_DBZH_20261019T1340": ("DBZH", digest)
        }), patch.object(xyz, "_load_existing_f13_renderer") as renderer:
            with self.assertRaisesRegex(
                    xyz.OriginalXYZProbeError,
                    "^source_metadata_not_confirmed$"):
                xyz.inspect_original_xyz(
                    self.source, reference="CIRRUS_DBZH_20261019T1340",
                    z=6, x=33, y=19)
            renderer.assert_not_called()
        with rasterio.open(self.source, "r+") as ds:
            ds.update_tags(date="20261019", time="134000")
            ds.set_band_description(1, "NOT_DBZH")
        digest = sha256(self.source.read_bytes()).hexdigest()
        with patch.dict(xyz.ORIGINALS, {
            "CIRRUS_DBZH_20261019T1340": ("DBZH", digest)
        }), patch.object(xyz, "_load_existing_f13_renderer") as renderer:
            with self.assertRaisesRegex(
                    xyz.OriginalXYZProbeError,
                    "^source_metadata_not_confirmed$"):
                xyz.inspect_original_xyz(
                    self.source, reference="CIRRUS_DBZH_20261019T1340",
                    z=6, x=33, y=19)
            renderer.assert_not_called()

    def test_invalid_coordinates_and_reference_fail_before_open(self):
        with patch.object(xyz, "_verified_private_snapshot") as open_source:
            for args in (
                dict(reference="CIRRUS_DBZH_20261019T1340", z=17, x=0, y=0),
                dict(reference="CIRRUS_DBZH_20261019T1340", z=6, x=64, y=19),
                dict(reference="CIRRUS_DBZH_20261019T1340", z=6, x=33, y=-1),
                dict(reference="CIRRUS_DBZH_20261019T1340", z=True, x=0, y=0),
                dict(reference="UNKNOWN", z=6, x=33, y=19),
            ):
                with self.subTest(args=str(args)):
                    with self.assertRaises(xyz.OriginalXYZProbeError):
                        xyz.inspect_original_xyz(self.source, **args)
            open_source.assert_not_called()

    def test_cli_failure_json_is_redacted_and_installation_blocked(self):
        from contextlib import redirect_stdout
        from io import StringIO
        import json
        buffer = StringIO()
        with redirect_stdout(buffer):
            status = xyz.main([
                "--reference", "CIRRUS_DBZH_20261019T1340",
                "--source", str(self.source),
                "--z", "6", "--x", "33", "--y", "19",
            ])
        value = json.loads(buffer.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(value["status"], "sha256_mismatch")
        self.assertEqual(value["ha_installation"], "BLOCKED")
        self.assertEqual(value["consumer_provider_activation"], "BLOCKED")
        self.assertNotIn(str(self.source), buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
