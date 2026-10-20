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
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def _wheel_tags():
    try:
        from packaging.tags import sys_tags
        # Report only Python-ABI-platform triplets; never local wheel paths.
        return [str(tag) for _, tag in zip(range(6), sys_tags())]
    except Exception:
        return []


def _native_import(timeout=8):
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", IMPORT_PROBE],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"native_import": "timeout"}
    except (OSError, ValueError):
        return {"native_import": "unavailable"}
    if result.returncode != 0:
        return {"native_import": "import_error"}
    try:
        data = json.loads(result.stdout)
    except (TypeError, ValueError):
        return {"native_import": "invalid_child_output"}
    state = data.get("native_import")
    if state not in ALLOWED_CHILD_STATES:
        return {"native_import": "invalid_child_output"}
    sanitized = {"native_import": state}
    if state == "ok":
        for key in ("rasterio", "gdal", "proj"):
            value = data.get(key)
            # A malicious/accidental version string must not leak raw output.
            if not isinstance(value, str) or not 1 <= len(value) <= 48:
                return {"native_import": "invalid_child_output"}
            if not all(ch.isalnum() or ch in ".-_+" for ch in value):
                return {"native_import": "invalid_child_output"}
            sanitized[key] = value
    return sanitized


def inventory():
    versions = {name.lower(): _package_version(name)
                for name in PACKAGE_NAMES}
    return {
        "schema": SCHEMA,
        "target": "currently_executing_python_only",
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "cache_tag": sys.implementation.cache_tag,
        "soabi": sysconfig.get_config_var("SOABI"),
        "sysconfig_platform": sysconfig.get_platform(),
        "architecture": platform.machine(),
        "libc": platform.libc_ver()[0] or "not_identified",
        "wheel_tags_head": _wheel_tags(),
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
