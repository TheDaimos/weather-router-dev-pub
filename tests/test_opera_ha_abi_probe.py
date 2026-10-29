"""F7 ABI inventory: allowlisted read-only output and native subprocess isolation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "probe_opera_ha_abi.py"
spec = importlib.util.spec_from_file_location("_wr_opera_ha_abi_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class TestHaAbiInventory(unittest.TestCase):
    def test_inventory_is_explicitly_not_an_installation_approval(self):
        with patch.object(probe, "_native_import", return_value={
            "native_import": "ok", "rasterio": "1.5.0",
            "gdal": "3.13.3", "proj": "9.8.1",
        }):
            report = probe.inventory()
        self.assertEqual(report["schema"], probe.SCHEMA)
        self.assertEqual(report["f7_ha_installation"], "BLOCKED")
        self.assertEqual(report["ha_supported_native_installation"],
                         "not_verified")
        self.assertEqual(report["ha_os_or_supervisor_version"], "not_probed")
        self.assertEqual(report["target"], "currently_executing_python_only")
        self.assertIn("soabi", report)
        self.assertIn("architecture", report)
        self.assertIsInstance(report["wheel_tags_head"], list)
        self.assertLessEqual(len(report["wheel_tags_head"]), 6)
        self.assertIn("homeassistant", report["installed_distributions"])
        # No full paths, usernames, endpoints, OS environment, or identifiers.
        for sensitive in ("hostname", "username", "path", "env", "token",
                          "lat", "lon", "serial", "home_directory"):
            self.assertNotIn(sensitive, report)

    def test_native_import_uses_bounded_isolated_subprocess(self):
        payload = json.dumps({
            "native_import": "ok", "rasterio": "1.5.0",
            "gdal": "3.13.3", "proj": "9.8.1",
        }).encode("ascii")
        with patch.object(probe, "_bounded_child_output",
                          return_value=(None, payload)) as run:
            report = probe._native_import()
        self.assertEqual(report["native_import"], "ok")
        self.assertNotIn("stderr", report)
        args, kwargs = run.call_args
        self.assertEqual(args[0], probe.IMPORT_PROBE)
        self.assertEqual(kwargs["timeout"], 8)

    def test_no_native_libraries_or_unexpected_stdout_never_approve(self):
        for exit_code, stdout, expected in (
            (1, "", "import_error"),
            (0, '{"native_import":"missing"}', "missing"),
            (0, '{"native_import":"ok","rasterio":"/tmp/private",'
                '"gdal":"3.13.3","proj":"9.8.1"}', "invalid_child_output"),
            (0, '{"native_import":"something_else"}',
                "invalid_child_output"),
            (0, "unparseable stderr data", "invalid_child_output"),
        ):
            with self.subTest(expected=expected, stdout=stdout):
                value = (("import_error", None) if exit_code
                         else (None, stdout.encode("utf-8")))
                with patch.object(probe, "_bounded_child_output",
                                  return_value=value):
                    report = probe._native_import()
                self.assertEqual(report, {"native_import": expected})

    def test_timeout_does_not_propagate_process_details(self):
        with patch.object(probe, "_bounded_child_output",
                          return_value=("timeout", None)):
            self.assertEqual(probe._native_import(),
                             {"native_import": "timeout"})

    def test_musllinux_wheel_tags_identify_musl_without_host_probes(self):
        """Alpine libc may be omitted by platform.libc_ver()."""
        with patch.object(probe, "_wheel_tags",
                          return_value=["cp314-cp314-musllinux_1_2_aarch64"]), \
             patch.object(probe.platform, "libc_ver", return_value=("", "")), \
             patch.object(probe, "_native_import",
                          return_value={"native_import": "missing"}):
            report = probe.inventory()
        self.assertEqual(report["libc"], "musl")
        self.assertEqual(report["wheel_tags_head"],
                         ["cp314-cp314-musllinux_1_2_aarch64"])
        self.assertEqual(report["f7_ha_installation"], "BLOCKED")
        with patch.object(probe.platform, "libc_ver", return_value=("", "")):
            self.assertEqual(probe._libc_class(
                ["cp313-cp313-manylinux_2_39_x86_64"]), "not_identified")
        with patch.object(probe.platform, "libc_ver",
                          return_value=("glibc", "2.39")):
            self.assertEqual(probe._libc_class(
                ["cp313-cp313-manylinux_2_39_x86_64"]), "glibc")

    def test_nonmapping_oversized_native_json_fails_closed(self):
        """One malformed child must never crash or echo its untrusted output."""
        invalid_samples = ("[]", "null", "12", '"secret"', "x" * 5000)
        for stdout in invalid_samples:
            with self.subTest(stdout_length=len(stdout)):
                with patch.object(probe, "_bounded_child_output",
                                  return_value=(None, stdout.encode("utf-8"))):
                    report = probe._native_import()
                self.assertEqual(report, {
                    "native_import": "invalid_child_output"})

    def test_invalid_utf8_and_package_metadata_do_not_escape(self):
        """No exception text, secret path or malformed version reaches JSON."""
        with patch.object(probe, "_bounded_child_output",
                          return_value=(None, b"\xff")):
            self.assertEqual(probe._native_import(),
                             {"native_import": "invalid_child_output"})
        with patch.object(probe.importlib.metadata, "version",
                          return_value="/home/secret/username"):
            self.assertIsNone(probe._package_version("rasterio"))
        with patch.object(probe.importlib.metadata, "version",
                          return_value="1.5.0"):
            self.assertEqual(probe._package_version("rasterio"), "1.5.0")

    def test_bounded_child_stdout_limits_memory_at_pipe_boundary(self):
        """Exactly 4096 bytes are accepted; the 4097th terminates the child."""
        for size, expected in ((4096, None), (4097, "invalid_child_output"),
                               (1_000_000, "invalid_child_output")):
            with self.subTest(size=size):
                code = ("import os; os.write(1, b'x' * " + str(size) + ")")
                status, data = probe._bounded_child_output(code, timeout=2)
                self.assertEqual(status, expected)
                if status is None:
                    self.assertEqual(len(data), 4096)
                else:
                    self.assertIsNone(data)

    def test_bounded_child_timeout_terminates_running_process(self):
        import time
        before = time.monotonic()
        status, data = probe._bounded_child_output(
            "import time;time.sleep(10)", timeout=0.15)
        self.assertEqual(status, "timeout")
        self.assertIsNone(data)
        self.assertLess(time.monotonic() - before, 2.0)

    def test_bounded_child_stderr_is_never_captured_or_serialized(self):
        code = ("import os,json; os.write(2,b'/private/token'); "
                "print(json.dumps({'native_import':'missing'}))")
        status, data = probe._bounded_child_output(code, timeout=2)
        self.assertIsNone(status)
        self.assertNotIn(b"private", data)
        self.assertEqual(json.loads(data), {"native_import": "missing"})

    def test_bounded_child_nonzero_exit_and_invalid_utf8_are_safe(self):
        status, data = probe._bounded_child_output(
            "import sys;sys.exit(5)", timeout=2)
        self.assertEqual((status, data), ("import_error", None))
        code = "import os;os.write(1,b'\\xff')"
        status, data = probe._bounded_child_output(code, timeout=2)
        self.assertIsNone(status)
        with patch.object(probe, "_bounded_child_output",
                          return_value=(status, data)):
            self.assertEqual(probe._native_import(),
                             {"native_import": "invalid_child_output"})

    def test_machine_report_is_valid_json_and_remains_blocked(self):
        with patch.object(probe, "_native_import",
                          return_value={"native_import": "missing"}), \
             patch.object(probe, "_package_version", return_value=None):
            obj = probe.inventory()
        encoded = json.dumps(obj)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["f7_ha_installation"], "BLOCKED")
        self.assertEqual(decoded["native_import"], "missing")
        self.assertEqual(decoded["installed_distributions"]["rasterio"], None)


if __name__ == "__main__":
    unittest.main()
