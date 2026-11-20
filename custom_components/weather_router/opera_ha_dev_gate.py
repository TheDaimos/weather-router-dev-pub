"""Fail-closed and read-only prerequisite gate for HA DEV OPERA diagnostics.

No package installations or modification of Home Assistant state.
"""
from __future__ import annotations

from collections.abc import Mapping

REQUIRED = ("Pillow", "numpy", "h5py", "pyproj")


def evaluate_dev_runtime(report: Mapping, *, expected_python: str,
                         expected_architecture: str,
                         expected_abi: str) -> dict:
    """Require an independently supplied VM109 ABI baseline and all imports.

    An importable development laptop is never a valid deployment assessment.
    """
    failures = []
    if not isinstance(report, Mapping) or report.get("target") != "HA_DEV_VM109_read_only":
        return {"ready_for_diagnostic_test": False,
                "blockers": ["untrusted_target_report"]}
    for name, value in (("python_version", expected_python),
                        ("architecture", expected_architecture),
                        ("python_abi", expected_abi)):
        if not isinstance(value, str) or not value.strip():
            failures.append(name + ":target_baseline_missing")
        elif report.get(name) != value:
            failures.append(name + ":target_mismatch")
    deps = report.get("package_imports")
    if not isinstance(deps, Mapping) or deps.get("runtime_importable") is not True:
        failures.append("native_imports_unavailable")
    else:
        versions = deps.get("dependencies")
        if not isinstance(versions, Mapping) or any(
                not isinstance(versions.get(name), str) or not versions[name]
                for name in REQUIRED):
            failures.append("dependency_versions_incomplete")
    if report.get("native_delivery_approved") is not False:
        failures.append("runtime_report_must_not_grant_deployment")
    return {
        "ready_for_diagnostic_test": not failures,
        "blockers": failures,
        "scientific_raster_approved": False,
        "production_install_approved": False,
    }
