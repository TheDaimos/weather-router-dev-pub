"""Bounded read-only OPERA checks executed in HA's executor on explicit admin request.

No pytest subprocess, network, source publication, registry mutation or raster admission.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
import time

MODULES = (
    "opera_odim_pixels.py",
    "opera_odim_tile.py",
    "opera_odim_reconstruction.py",
    "opera_v2_admission.py",
    "opera_tile_http.py",
)
MAX_SOURCE_BYTES = 512 * 1024


def run_scientific_selfcheck() -> dict:
    """Inspect the actually installed modules, without claiming a rendered-image test."""
    started = time.monotonic()
    root = Path(__file__).resolve().parent
    checks = []
    for name in MODULES:
        target = root / name
        status = "failed"
        reason = "source_unavailable"
        try:
            if target.is_symlink() or not target.is_file():
                raise ValueError("source_unavailable")
            size = target.stat().st_size
            if not 0 < size <= MAX_SOURCE_BYTES:
                raise ValueError("source_size_invalid")
            source = target.read_bytes()
            ast.parse(source, filename=name)
            status, reason = "passed", "python_syntax_valid"
        except SyntaxError:
            reason = "python_syntax_invalid"
        except (OSError, UnicodeError, ValueError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) and str(exc) in (
                "source_unavailable", "source_size_invalid") else "source_read_failed"
        checks.append({"id": name.removesuffix(".py"), "status": status, "reason": reason})

    # Offline-only runtime import probe. Never import native raster packages
    # on the Home Assistant event loop (caller must use executor).
    dependencies = []
    from importlib.util import find_spec
    for name in ("numpy", "h5py", "pyproj", "PIL"):
        try:
            available = find_spec(name) is not None
        except (ImportError, ValueError):
            available = False
        dependencies.append({"id": name, "status": "available" if available else "missing"})

    # Missing native dependencies invalidate the preflight; never report green
    # when the real installed decoder cannot import its scientific libraries.
    syntax_ok = all(item["status"] == "passed" for item in checks)
    dependencies_ok = all(item["status"] == "available" for item in dependencies)
    ok = syntax_ok and dependencies_ok
    return {
        "schema": "weather_router.opera.scientific_selfcheck.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "preflight_passed" if ok else "preflight_failed",
        "checks": checks,
        "dependencies": dependencies,
        "syntax_ok": syntax_ok,
        "dependencies_ok": dependencies_ok,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        "executed": ["installed_module_ast", "dependency_presence"],
        "not_executed": [
            "pytest_suite", "original_hdf5_tiff_pixel_comparison",
            "productive_tile_geometry", "rgba_palette_and_quality",
            "http_authorization", "consumer_api_v2_end_to_end", "ha_dev_real_acceptance",
        ],
        "scientific_raster_approved": False,
        "dra_candidate_approved": False,
    }
