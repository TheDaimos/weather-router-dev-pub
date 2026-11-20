"""Read-only OPERA RATE native dependency preflight for Home Assistant DEV.

Never installs libraries, enables the provider, or substitutes for an actual
HAOS ABI / wheel provenance and licensing check.
"""
from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version


PACKAGES = ("Pillow", "numpy", "h5py", "pyproj")


def inspect_rate_runtime() -> dict:
    """Return explicit blockers; import success alone is not installation approval."""
    found = {}
    blockers = []
    for distribution in PACKAGES:
        try:
            found[distribution] = version(distribution)
        except (PackageNotFoundError, ValueError):
            found[distribution] = None
            blockers.append(f"{distribution}:distribution_missing")
            continue
        module = "PIL.Image" if distribution == "Pillow" else distribution
        try:
            import_module(module)
        except (ImportError, OSError, RuntimeError, ValueError):
            blockers.append(f"{distribution}:native_import_failed")
    return {
        "component": "opera_rate_png",
        "dependencies": found,
        "runtime_importable": not blockers,
        "blockers": blockers,
        "ha_dev_install_approved": False,
        "scientific_raster_approved": False,
        "reason": "requires_independent_source_pixel_and_haos_abi_validation",
    }
