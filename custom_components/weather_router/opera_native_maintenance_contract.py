"""F7 release maintenance diff: new native versions ALWAYS require new evidence.

No network, import, install, or activation. Contract is intentionally strict.
"""
from __future__ import annotations
import re

HEX=re.compile(r"[0-9a-f]{64}\Z")
FIELDS=("python_soabi","wheel_sha256","rasterio","gdal","proj",
        "alpine_image_digest","apk_db_sha256","license_matrix_sha256",
        "security_advisory_snapshot_sha256")

def compare(previous,next_release):
    if not isinstance(previous,dict) or not isinstance(next_release,dict):
        raise ValueError("invalid_releases")
    if set(previous)!=set(FIELDS) or set(next_release)!=set(FIELDS):
        raise ValueError("incomplete_release_provenance")
    for value in (previous,next_release):
        for key in FIELDS:
            v=value[key]
            if not isinstance(v,str) or len(v)>180 or not v:
                raise ValueError("invalid_release_value")
        for key in ("wheel_sha256","apk_db_sha256","license_matrix_sha256",
                    "security_advisory_snapshot_sha256"):
            if HEX.fullmatch(value[key]) is None:
                raise ValueError("invalid_provenance_hash")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}",value["alpine_image_digest"]):
            raise ValueError("invalid_alpine_digest")
    changed=[key for key in FIELDS if previous[key]!=next_release[key]]
    return {
        "schema":"weather_router.f7.native_maintenance_comparison.v1",
        "changed_fields":changed,
        "requires_new_full_license_and_cve_review":True,
        "requires_new_isolated_dual_build":True,
        "requires_native_abi_and_ha_compatibility_test":True,
        "manual_activation_decision_required":True,
        "existing_native_free_v1_v2_preserved":True,
        "safe_auto_upgrade":False,
        "approved_new_release":False,
        "distribution":"BLOCKED",
        "ha_installation":"BLOCKED",
        "opera_activation":"BLOCKED"
    }
