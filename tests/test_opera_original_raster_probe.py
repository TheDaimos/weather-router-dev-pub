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

    def test_source_change_after_hash_cannot_change_scanned_pixels(self):
        """A path changed before GDAL opens is not the checked source bytes."""
        from unittest.mock import patch
        actual_open = rasterio.open
        opened_paths = []

        def mutate_original_then_open(source, *args, **kwargs):
            opened_paths.append(Path(source))
            self.assertNotEqual(Path(source), self.path)
            # Simulates a different file in the caller-controlled source path.
            self.path.write_bytes(b"untrusted source modified after checksum")
            return actual_open(source, *args, **kwargs)

        with patch.object(rasterio, "open", side_effect=mutate_original_then_open):
            result = probe.inspect_file(self.path, product="DBZH",
                                        expected_sha256=self.digest)
        self.assertEqual(result["sha256"], self.digest)
        self.assertEqual(result["pixel_counts"]["valid_negative"], 1)
        self.assertEqual(result["pixel_counts"]["valid_positive"], 3)
        self.assertEqual(len(opened_paths), 1)
        self.assertFalse(opened_paths[0].exists())
        self.assertEqual(result["ha_installation"], "BLOCKED")

    def test_private_verified_snapshot_permissions_and_cleanup(self):
        import os
        import stat
        with probe._verified_private_snapshot(self.path, self.digest) as (snap, size, digest):
            self.assertTrue(snap.is_file())
            self.assertNotEqual(snap, self.path)
            self.assertEqual(size, self.path.stat().st_size)
            self.assertEqual(digest, self.digest)
            self.assertEqual(stat.S_IMODE(snap.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(snap.parent.stat().st_mode), 0o700)
            self.assertEqual(snap.read_bytes(), self.path.read_bytes())
        self.assertFalse(snap.exists())
        self.assertFalse(snap.parent.exists())

    def test_symlink_replacement_at_open_is_rejected(self):
        """O_NOFOLLOW rejects a swap even after the initial path precheck."""
        from unittest.mock import patch
        real_os_open = probe.os.open
        other = Path(self.temp.name) / "other.tiff"
        other.write_bytes(b"untrusted")
        switched = []

        def swap_before_open(path, *args, **kwargs):
            if Path(path) == self.path and not switched:
                switched.append(True)
                self.path.unlink()
                self.path.symlink_to(other)
            return real_os_open(path, *args, **kwargs)

        with patch.object(probe.os, "open", side_effect=swap_before_open):
            with self.assertRaisesRegex(probe.OriginalRasterProbeError,
                                        "invalid_local_source"):
                probe.inspect_file(self.path, product="DBZH",
                                   expected_sha256=self.digest)
        self.assertTrue(switched)

    def test_native_errors_do_not_leak_paths_and_snapshot_is_cleaned(self):
        from unittest.mock import patch
        with patch.object(rasterio, "open",
                          side_effect=RuntimeError("/secret/native/error")) as opened:
            with self.assertRaisesRegex(probe.OriginalRasterProbeError,
                                        "^raster_inspection_failed$"):
                probe.inspect_file(self.path, product="DBZH",
                                   expected_sha256=self.digest)
        staged = Path(opened.call_args.args[0])
        self.assertNotEqual(staged, self.path)
        self.assertFalse(staged.exists())
        self.assertFalse(staged.parent.exists())

    def test_preflight_rejection_closes_source_fd(self):
        """Type and size fail-closed paths must not leak the open descriptor."""
        import os
        from unittest.mock import patch
        empty = Path(self.temp.name) / "zero-byte.tiff"
        empty.touch()
        oversize = Path(self.temp.name) / "oversize.tiff"
        with oversize.open("wb") as f:
            f.truncate(probe.MAX_BYTES + 1)
        directory = Path(self.temp.name)
        real_close = os.close
        for candidate, error in (
            (empty, "invalid_source_size"),
            (oversize, "invalid_source_size"),
            (directory, "invalid_local_source"),
        ):
            with self.subTest(error=error, candidate=candidate.name):
                with patch.object(probe.os, "close", wraps=real_close) as closing:
                    with self.assertRaisesRegex(probe.OriginalRasterProbeError, error):
                        probe.inspect_file(
                            candidate, product="DBZH", expected_sha256=self.digest)
                    self.assertEqual(closing.call_count, 1, "leaked_source_fd")

    def test_fstat_failure_closes_source_fd_and_redacts_native_error(self):
        """An OSError after os.open must close FD and suppress its message."""
        import os
        from unittest.mock import patch
        real_close = os.close
        with patch.object(probe.os, "fstat",
                          side_effect=OSError("/private/secret/source")), \
             patch.object(probe.os, "close", wraps=real_close) as closing:
            with self.assertRaisesRegex(
                    probe.OriginalRasterProbeError, "^invalid_local_source$"):
                probe.inspect_file(
                    self.path, product="DBZH", expected_sha256=self.digest)
            self.assertEqual(closing.call_count, 1, "leaked_source_fd")

    def test_nonfile_and_symlink_rejected(self):
        link = Path(self.temp.name) / "link.tiff"
        link.symlink_to(self.path)
        for candidate in (link, Path(self.temp.name) / "missing.tiff"):
            with self.subTest(candidate=candidate.name):
                with self.assertRaisesRegex(probe.OriginalRasterProbeError, "invalid_local_source"):
                    probe.inspect_file(candidate, product="RATE", expected_sha256=self.digest)


if __name__ == "__main__":
    unittest.main()
