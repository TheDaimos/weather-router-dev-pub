"""WeatherRouter F7: strictly read-only, redacted HA Python ABI inventory.

Invoke ONLY as an explicit command in an approved development/test container.
Does not install libraries, register HTTP endpoints, contact networks, load
providers, access HA configuration, or execute any raster work. Output contains
only allowlisted runtime/package fields, never environment variables or paths.
This inventory does not constitute permission to install OPERA or activate F7.
"""
from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import subprocess
import sys
import sysconfig


SCHEMA = "weather_router.opera.ha_abi_inventory.v1"
PACKAGE_NAMES = ("homeassistant", "numpy", "Pillow", "rasterio")
ALLOWED_CHILD_STATES = ("ok", "missing", "import_error")

# Use a separate, bounded process to avoid loading GDAL/PROJ in the parent.
# The child reports only a fixed, allowlisted set of fields and no exception
# messages or full version banners (those might contain sensitive paths).
IMPORT_PROBE = r"""
import json
probe = {"native_import": "ok"}
try:
    import numpy
    import PIL.Image
    import rasterio
    from rasterio.warp import reproject
except ImportError:
    probe["native_import"] = "missing"
except Exception:
    probe["native_import"] = "import_error"
else:
    probe["rasterio"] = rasterio.__version__
    probe["gdal"] = rasterio.__gdal_version__
    probe["proj"] = rasterio.__proj_version__
print(json.dumps(probe, sort_keys=True))
"""


def _package_version(package):
    try:
        raw = importlib.metadata.version(package)
    except Exception:
        return None
    # Malformed package metadata must not put arbitrary text into a report.
    if not isinstance(raw, str) or not re.fullmatch(
        r"[0-9][0-9A-Za-z.!+_-]{0,47}", raw, flags=re.ASCII
    ):
        return None
    return raw


def _wheel_tags():
    try:
        from packaging.tags import sys_tags
    except ImportError:
        # Home Assistant/CI may have pip but not a separately installed
        # "packaging" distribution; pip's bundled tag parser is read-only.
        try:
            from pip._vendor.packaging.tags import sys_tags
        except ImportError:
            return []
    try:
        # Report only Python-ABI-platform triplets; never wheel file paths.
        return [str(tag) for _, tag in zip(range(6), sys_tags())]
    except Exception:
        return []


def _libc_class(wheel_tags):
    """Classify musl without reading host files or running OS commands."""
    if any(isinstance(tag, str) and "-musllinux_" in tag for tag in wheel_tags):
        return "musl"
    try:
        libc_name = platform.libc_ver()[0]
    except Exception:
        libc_name = ""
    return "glibc" if libc_name in ("glibc", "GNU libc") else "not_identified"


def _bounded_child_output(code, timeout=8, max_bytes=4096):
    """Read at most max_bytes+1 from a native child and kill on timeout.

    Unlike subprocess.run(capture_output=True), this cannot buffer unbounded
    native library output. Never return child stderr or native exception text.
    Linux/HA only: select() handles a pipe without reading arbitrary output.
    """
    import os
    import selectors
    import time

    deadline = time.monotonic() + timeout
    process = None
    selector = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", code],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        result = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout", None
            events = selector.select(remaining)
            if not events:
                return "timeout", None
            # If the next chunk would exceed the budget, abort immediately.
            chunk = os.read(process.stdout.fileno(),
                            min(max_bytes + 1 - len(result), 4097))
            if not chunk:
                break
            result.extend(chunk)
            if len(result) > max_bytes:
                return "invalid_child_output", None
        try:
            status = process.wait(timeout=max(0.001, deadline-time.monotonic()))
        except subprocess.TimeoutExpired:
            return "timeout", None
        if status:
            return "import_error", None
        return None, bytes(result)
    except (OSError, ValueError):
        return "unavailable", None
    finally:
        if selector is not None:
            selector.close()
        if process is not None:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
            try:
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process.stdout is not None:
                process.stdout.close()


def _native_import(timeout=8):
    state, raw = _bounded_child_output(IMPORT_PROBE, timeout=timeout)
    if state is not None:
        return {"native_import": state}
    try:
        data = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, AttributeError, TypeError, ValueError):
        return {"native_import": "invalid_child_output"}
    if not isinstance(data, dict):
        return {"native_import": "invalid_child_output"}
    state = data.get("native_import")
    if state not in ALLOWED_CHILD_STATES:
        return {"native_import": "invalid_child_output"}
    sanitized = {"native_import": state}
    if state == "ok":
        for key in ("rasterio", "gdal", "proj"):
            value = data.get(key)
            if not isinstance(value, str) or not re.fullmatch(
                r"[0-9][0-9A-Za-z.+_-]{0,47}", value, flags=re.ASCII
            ):
                return {"native_import": "invalid_child_output"}
            sanitized[key] = value
    return sanitized


def inventory():
    versions = {name.lower(): _package_version(name)
                for name in PACKAGE_NAMES}
    wheel_tags = _wheel_tags()
    return {
        "schema": SCHEMA,
        "target": "currently_executing_python_only",
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "cache_tag": sys.implementation.cache_tag,
        "soabi": sysconfig.get_config_var("SOABI"),
        "sysconfig_platform": sysconfig.get_platform(),
        "architecture": platform.machine(),
        "libc": _libc_class(wheel_tags),
        "wheel_tags_head": wheel_tags,
        "installed_distributions": versions,
        **_native_import(),
        "ha_os_or_supervisor_version": "not_probed",
        "ha_supported_native_installation": "not_verified",
        "f7_ha_installation": "BLOCKED",
    }


def main():
    print(json.dumps(inventory(), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
