"""Read-only OPERA original forensic helper; synthetic data are not OPERA."""
import importlib.util
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

import numpy as np
import rasterio
from rasterio.transform import from_origin

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/probe_opera_original_raster.py"
spec = importlib.util.spec_from_file_location("_wr_original_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class OriginalRasterProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "synthetic.tiff"
        self.pixels = np.array([[-8, 0, 25, -9999000], [np.nan, 8, 2, -9999000]], dtype="float32")
        self.quality = np.array([[0, 0.8, 0.2, -9999000], [np.nan, 0, 0, -9999000]], dtype="float32")
        with rasterio.open(self.path, "w", driver="GTiff", width=4, height=2, count=2,
                           dtype="float32", crs="EPSG:4326", nodata=-9999000,
                           transform=from_origin(0, 2, 1, 1)) as dst:
            dst.write(self.pixels, 1)
            dst.write(self.quality, 2)
        self.digest = sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def test_counts_valid_negative_zero_nan_sentinel_and_quality_without_filtering(self):
        v = probe.inspect_file(self.path, product="DBZH", expected_sha256=self.digest)
        counts = v["pixel_counts"]
        self.assertEqual(counts["total"], 8)
        self.assertEqual(counts["nan"], 1)
        self.assertEqual(counts["infinite"], 0)
        self.assertEqual(counts["sentinel"], 2)
        self.assertEqual(counts["valid_negative"], 1)
        self.assertEqual(counts["valid_zero"], 1)
        self.assertEqual(counts["valid_positive"], 3)
        self.assertEqual(counts["quality_zero_on_valid"], 3)
        self.assertEqual(counts["quality_positive_on_valid"], 2)
        self.assertEqual(v["quality1_scientific_meaning"], "unverified")
        self.assertEqual(v["consumer_provider_activation"], "BLOCKED")
        self.assertEqual(v["ha_real_acceptance"], "NOT_TESTED")
        self.assertNotIn(str(self.path), str(v))

    def test_rate_product_never_inferred_from_dbzh_measurement(self):
        v = probe.inspect_file(self.path, product="RATE", expected_sha256=self.digest)
        self.assertEqual(v["unit"], "mm/h")
        self.assertEqual(v["pixel_counts"]["valid_zero"], 1)
        self.assertEqual(v["color_palette"], "unverified")
        self.assertEqual(v["ha_installation"], "BLOCKED")

    def test_wrong_checksum_fails_before_any_native_raster_open(self):
        with self.assertRaisesRegex(probe.OriginalRasterProbeError, "sha256_mismatch"):
            probe.inspect_file(self.path, product="DBZH", expected_sha256="0" * 64)

    def test_nonfile_and_symlink_rejected(self):
        link = Path(self.temp.name) / "link.tiff"
        link.symlink_to(self.path)
        for candidate in (link, Path(self.temp.name) / "missing.tiff"):
            with self.subTest(candidate=candidate.name):
                with self.assertRaisesRegex(probe.OriginalRasterProbeError, "invalid_local_source"):
                    probe.inspect_file(candidate, product="RATE", expected_sha256=self.digest)


if __name__ == "__main__":
    unittest.main()
