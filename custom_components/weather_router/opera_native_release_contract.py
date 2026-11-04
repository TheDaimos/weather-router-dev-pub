"""WeatherRouter F7 P1-L02: passive internal native package decision contract.

No I/O, archive extraction, imports, path/environment mutation, or activation.
Actual native access remains impossible by design. An offline audit decision
cannot be formed from self-reported license/provenance flags in a wheel.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

ABI = "cp314-cp314-musllinux_1_2_x86_64"
SOABI = "cpython-314-x86_64-linux-musl"
WHEEL = "rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl"
SHA = re.compile(r"[a-f0-9]{64}\Z")
CONTRACT = "weather_router.f7.passive_native_release.v1"
MAX_WORKERS = 2
MAX_CANDIDATE_MIB = 250
MAX_EXPANDED_MIB = 700

class NativeReleaseContractError(ValueError):
    """Invalid or untrustworthy F7 native package descriptor."""

def _string(value, length=256):
    return isinstance(value, str) and 0 < len(value) <= length

def check_descriptor(descriptor: Mapping, *, actual_soabi: str | None,
                     trusted_digest: str | None) -> dict:
    """Validate a candidate against an *externally supplied* pinned digest.

    This is a metadata/integrity check, never a license or provenance approval.
    A consumer MUST NOT derive trusted_digest from descriptor or candidate ZIP.
    """
    if not isinstance(descriptor, Mapping):
        raise NativeReleaseContractError("invalid_descriptor")
    if set(descriptor) != {"schema","wheel_name","wheel_sha256","abi","python_soabi",
                           "rasterio","gdal","proj","max_worker_count",
                           "max_archive_mib","max_uncompressed_mib","release_id"}:
        raise NativeReleaseContractError("descriptor_shape")
    if descriptor["schema"] != CONTRACT or descriptor["wheel_name"] != WHEEL:
        raise NativeReleaseContractError("descriptor_schema_or_wheel")
    if descriptor["abi"] != ABI or descriptor["python_soabi"] != SOABI:
        raise NativeReleaseContractError("abi_mismatch")
    if tuple(descriptor[x] for x in ("rasterio","gdal","proj")) != ("1.5.2","3.13.3","9.8.1"):
        raise NativeReleaseContractError("native_version_mismatch")
    digest=descriptor["wheel_sha256"]
    if not _string(digest,64) or SHA.fullmatch(digest) is None:
        raise NativeReleaseContractError("invalid_digest")
    if trusted_digest is None or not _string(trusted_digest,64) or SHA.fullmatch(trusted_digest) is None:
        raise NativeReleaseContractError("independently_trusted_digest_missing")
    if digest != trusted_digest:
        raise NativeReleaseContractError("trusted_digest_mismatch")
    if actual_soabi != SOABI:
        raise NativeReleaseContractError("ha_python_abi_incompatible")
    if not _string(descriptor["release_id"],80) or not re.fullmatch(
            r"[a-z0-9][a-z0-9.-]{0,79}",descriptor["release_id"]):
        raise NativeReleaseContractError("invalid_release_id")
    for key, cap in (("max_worker_count",MAX_WORKERS),
                     ("max_archive_mib",MAX_CANDIDATE_MIB),
                     ("max_uncompressed_mib",MAX_EXPANDED_MIB)):
        v=descriptor[key]
        if type(v) is not int or not 1<=v<=cap:
            raise NativeReleaseContractError("resource_limit_invalid")
    return {"status":"DESCRIPTOR_AND_TRUSTED_DIGEST_MATCH_ONLY",
            "release_id":descriptor["release_id"],
            "sha256":digest, "abi":ABI,
            "max_workers":descriptor["max_worker_count"],
            "memory_limit_proven":False,
            "license_cleared":False,"security_cleared":False,
            "source_attested":False,"native_import_enabled":False,
            "ha_installation":"BLOCKED","opera_activation":"BLOCKED"}

class PassiveNativeRelease:
    """Local ephemeral decision trace; revocation cannot be undone by descriptor.

    It prepares NO runnable native binaries, and contains no activation method.
    A future loader is deliberately NOT part of this class.
    """
    def __init__(self):
        self._state="DISABLED"
        self._history=[]
        self._candidate=None

    def inspect(self, descriptor: Mapping, *, actual_soabi: str | None,
                trusted_digest: str | None) -> dict:
        if self._state=="REVOKED":
            return self.diagnose("revoked_requires_new_session")
        try:
            checked=check_descriptor(descriptor,actual_soabi=actual_soabi,
                                     trusted_digest=trusted_digest)
        except NativeReleaseContractError as exc:
            self._state="DENIED"
            self._candidate=None
            self._history.append(str(exc))
            return self.diagnose(str(exc))
        self._state="CANDIDATE_PASSIVE_ONLY"
        self._candidate=checked
        self._history.append("candidate_metadata_only")
        return self.diagnose("license_security_attestation_and_manual_activation_missing")

    def revoke(self) -> dict:
        self._state="REVOKED"
        self._candidate=None
        self._history.append("manual_revoke")
        return self.diagnose("revoked")

    def rollback(self) -> dict:
        # Failback to native-free V1/V2 is ALWAYS permitted, never imports native.
        self._state="DISABLED" if self._state!="REVOKED" else "REVOKED"
        self._candidate=None
        self._history.append("native_free_fallback")
        return self.diagnose("native_free_v1_v2_fallback")

    def diagnose(self, reason: str="not_enabled") -> dict:
        return {
            "schema":"weather_router.f7.passive_native_decision.v1",
            "state":self._state,"reason":reason,
            "candidate_sha256":(self._candidate or {}).get("sha256"),
            "native_activation_possible":False,
            "approval_signatures_verified":False,
            "licenses_cleared":False,
            "vulnerability_review_cleared":False,
            "source_provenance_attested":False,
            "max_parallel_native_workers":0,
            "native_runtime_cpu_memory_limits_enforced":False,
            "fallback":"EXISTING_NATIVE_FREE_V1_V2",
            "ha_installation":"BLOCKED","opera_provider":"BLOCKED"}
