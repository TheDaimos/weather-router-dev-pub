"""WeatherRouter F7 passive native supply contract – no imports, installs or IO.

No manifest requirements, sys.path, dlopen or OPERA registration. Data from a
candidate is never authority: independent approval attestations are required.
All decisions remain blocked pending HA operator approval and real tests.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

SHA = re.compile(r"[a-f0-9]{64}\Z")
ABI = "cp314-cp314-musllinux_1_2_x86_64"
PACKAGE = "rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl"
CAP_CPU_WORKERS = 2
CAP_QUEUED = 6
CAP_EXEC_SECONDS = 16
REQUIRED_EVIDENCE = ("source_provenance", "native_licenses", "security_review",
                     "complete_sbom", "artifact_signature", "ha_dev_approval")

@dataclass(frozen=True)
class PassiveDecision:
    status: str
    reason: str
    active: bool = False
    may_install: bool = False
    may_import: bool = False

    def diagnostic(self):
        return {"status": self.status, "reason": self.reason,
                "active": self.active, "may_install": self.may_install,
                "may_import": self.may_import,
                "max_workers": CAP_CPU_WORKERS,
                "max_queued": CAP_QUEUED,
                "execution_target_seconds": CAP_EXEC_SECONDS,
                "timeout_is_not_hard_native_abort": True}

def inspect_descriptor(descriptor, approvals, *, runtime=None):
    """Validate structured **external** approval claims; never execute them.

    Even a fully valid, signed external approval remains non-activating here,
    because there is no approved real HA native loader or operator consent.
    """
    if not isinstance(descriptor, dict):
        return PassiveDecision("BLOCKED", "descriptor_missing")
    if descriptor.get("schema") != "weather_router.f7.native_package.v1":
        return PassiveDecision("BLOCKED", "descriptor_schema")
    if descriptor.get("package") != PACKAGE or descriptor.get("abi") != ABI:
        return PassiveDecision("BLOCKED", "package_or_abi_mismatch")
    if descriptor.get("rasterio") != "1.5.2" or descriptor.get("gdal") != "3.13.3" or descriptor.get("proj") != "9.8.1":
        return PassiveDecision("BLOCKED", "native_version_mismatch")
    if not isinstance(descriptor.get("sha256"), str) or not SHA.fullmatch(descriptor["sha256"]):
        return PassiveDecision("BLOCKED", "hash_missing_or_invalid")
    if (not isinstance(runtime, dict)
            or runtime.get("implementation") != "CPython"
            or runtime.get("python_tag") != "cp314"
            or runtime.get("libc") != "musl"
            or runtime.get("architecture") != "x86_64"):
        return PassiveDecision("BLOCKED", "runtime_abi_unverified")
    if not isinstance(approvals, dict):
        return PassiveDecision("BLOCKED", "independent_approvals_missing")
    for key in REQUIRED_EVIDENCE:
        record = approvals.get(key)
        if (not isinstance(record, dict) or record.get("verified") is not True
                or record.get("artifact_sha256") != descriptor["sha256"]
                or not isinstance(record.get("evidence_ref"), str)
                or not record["evidence_ref"].strip()):
            return PassiveDecision("BLOCKED", "evidence_missing_" + key)
    # This subsystem has no authority to activate an operator's installation.
    return PassiveDecision("BLOCKED", "ha_install_and_opera_activation_not_authorized")

def rollback_contract(*, selected=None, previous=None):
    """Describe but DO NOT execute a rollback; provider fallback stays V1/V2."""
    return {"schema": "weather_router.f7.native_rollback.v1",
            "requested_package": selected, "previous_package": previous,
            "status": "NOT_EXECUTED",
            "fallback": "existing_v1_v2_without_rasterio",
            "native_import": "FORBIDDEN",
            "ha_installation": "BLOCKED",
            "opera_activation": "BLOCKED"}
