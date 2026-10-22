"""F7: cross-container build evidence, not signed provenance or deploy approval.

Reads two isolated build JSONs and a *read-only* repaired wheel differential.
Never opens wheel binaries, imports Rasterio, or installs anything.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys

MAX=2*1024*1024
HEX=re.compile(r"[0-9a-f]{64}\Z")

def read(path):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or not 0<p.stat().st_size<=MAX:
        raise ValueError("invalid_input")
    return json.loads(p.read_text(encoding="utf-8"))

def assess(left,right,comparison):
    if (left.get("schema")!="weather_router.f7.build_input_snapshot.v1"
            or right.get("schema")!=left["schema"]
            or left.get("status")!="EVIDENCE_ONLY_NOT_REPRODUCIBLE"
            or right.get("status")!="EVIDENCE_ONLY_NOT_REPRODUCIBLE"
            or comparison.get("schema")!="weather_router.f7.repaired_double_comparison.v1"):
        raise ValueError("unknown_report")
    la=left.get("wheel_sha256");ra=right.get("wheel_sha256")
    if any(not isinstance(x,str) or HEX.fullmatch(x) is None for x in (la,ra)):
        raise ValueError("invalid_candidate_hashes")
    if comparison.get("first_sha256")!=la or comparison.get("second_sha256")!=ra:
        raise ValueError("repaired_hash_cross_validation_failed")
    imageleft=left.get("container_image_digest")
    imageright=right.get("container_image_digest")
    same_image=(imageleft is not None and imageleft==imageright
                and bool(re.fullmatch(r"sha256:[0-9a-f]{64}",str(imageleft))))
    same_apks=(left.get("apk_db_sha256")==right.get("apk_db_sha256")
               and left.get("apk_packages")==right.get("apk_packages"))
    same_wheel=(la==ra and comparison.get("different_member_count")==0
                and comparison.get("status")=="BIT_IDENTICAL_UNAPPROVED")
    return {
        "schema":"weather_router.f7.cross_container_build_comparison.v1",
        "status":"BIT_IDENTICAL_UNAPPROVED" if same_wheel else "DIFFERENT_UNAPPROVED",
        "same_pinned_image_manifest_digest":same_image,
        "same_apk_installed_database_and_package_versions":same_apks,
        "same_repaired_wheel_sha256":same_wheel,
        "first_sha256":la,"second_sha256":ra,
        "different_member_count":comparison.get("different_member_count"),
        "image_digest":imageleft if same_image else None,
        "apk_db_sha256":left.get("apk_db_sha256") if same_apks else None,
        "apk_archive_shas_attested":False,
        "source_tarball_independently_attested":False,
        "toolchain_provenance_signed":False,
        "independent_build_host_attested":False,
        "license_review":"REQUIRED","security_review":"REQUIRED",
        "distribution":"BLOCKED","ha_installation":"BLOCKED",
        "opera_activation":"BLOCKED"}

def main(argv):
    if len(argv)!=4:
        print("usage: f7_cross_container_evidence.py FIRST_BUILD_JSON SECOND_BUILD_JSON REPAIRED_COMPARISON_JSON",file=sys.stderr)
        return 2
    try:
        result=assess(*(read(p) for p in argv[1:]))
    except (ValueError,OSError,UnicodeError,TypeError,KeyError):
        print("F7 cross-container comparison rejected",file=sys.stderr)
        return 1
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv))
