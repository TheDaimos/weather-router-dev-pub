"""F7 source-to-repaired-binary evidence gate, purely observational.

Cross-check same SHA-bound 101-ELF inventory against the official-Alpine
candidate, original-member and license-document reports. The result never
authorizes installation, signature trust or distribution. No native IO.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

HEX=re.compile(r"[a-f0-9]{64}\Z")
N=101
def assess(installed,archives,license_docs):
    expected=("weather_router.f7.apk_embedded_binary_comparison.v1",
              "weather_router.f7.apk_signed_member_correlation.v1",
              "weather_router.f7.apk_original_license_docs.v1")
    if tuple(x.get("schema") for x in (installed,archives,license_docs))!=expected:
        raise ValueError("schema_mismatch")
    wheel=installed.get("wheel_sha256")
    if not isinstance(wheel,str) or not HEX.fullmatch(wheel) or any(x.get("wheel_sha256")!=wheel for x in (archives,license_docs)):
        raise ValueError("wheel_binding_mismatch")
    groups=[installed.get("elf_components"),archives.get("elf_components")]
    if any(not isinstance(x,list) or len(x)!=N for x in groups):
        raise ValueError("incomplete_101_elf_list")
    if installed.get("native_elf_count")!=N or archives.get("native_elf_count")!=N:
        raise ValueError("bad_component_count")
    left={};right={}
    for record in groups[0]:
        name=record.get("wheel_path")
        digest=record.get("wheel_sha256")
        if not isinstance(name,str) or name in left or not isinstance(digest,str) or not HEX.fullmatch(digest):
            raise ValueError("invalid_installed_record")
        left[name]=record
    for record in groups[1]:
        name=record.get("wheel_path")
        digest=record.get("wheel_sha256")
        if name in right or not isinstance(name,str) or not isinstance(digest,str) or not HEX.fullmatch(digest):
            raise ValueError("invalid_archive_record")
        right[name]=record
    if set(left)!=set(right):
        raise ValueError("native_name_mismatch")
    classes={}
    positive=0
    for name in sorted(left):
        a,b=left[name],right[name]
        if a["wheel_sha256"]!=b["wheel_sha256"]:
            raise ValueError("native_file_digest_mismatch")
        state=b.get("status")
        if state not in ("SIGNED_APK_MEMBER_EQUALS_WHEEL_ELF_KEY_NOT_INDEPENDENT",
                         "SIGNED_APK_MEMBER_EQUALS_INSTALLED_NOT_REPAIRED_ELF",
                         "RASTERIO_SOURCE_WHEEL_NO_ALPINE_APK",
                         "APK_BINARY_OR_SIGNATURE_NOT_VERIFIED"):
            raise ValueError("unknown_native_provenance")
        if b.get("auditwheel_transformation_reproduced_from_apk") is not False or b.get("independent_key_trust") is not False:
            raise ValueError("unjustified_provenance_approval")
        matches=b.get("signed_archive_matches")
        if not isinstance(matches,list):
            raise ValueError("missing_archive_matches")
        if state.startswith("SIGNED_APK_MEMBER") and not matches:
            raise ValueError("signed_member_without_member_evidence")
        for match in matches:
            if (match.get("apk_elf_sha256")!=a.get("original_installed_sha256")
                    or not isinstance(match.get("apk_sha256"),str)
                    or not HEX.fullmatch(match["apk_sha256"])
                    or match.get("external_key_attestation") is not False):
                raise ValueError("apk_member_evidence_mismatch")
        classes[state]=classes.get(state,0)+1
        if matches:
            positive+=1
    if positive!=archives.get("archive_elf_matches_installed_count"):
        raise ValueError("reported_match_count_mismatch")
    if installed.get("ha_installation")!="BLOCKED" or archives.get("ha_installation")!="BLOCKED" or license_docs.get("ha_installation")!="BLOCKED":
        raise ValueError("installation_gate_not_blocked")
    if license_docs.get("original_copyright_and_distribution_obligations_reviewed") is not False:
        raise ValueError("unverified_license_clearance")
    return {"schema":"weather_router.f7.original_binary_release_gate.v1",
            "wheel_sha256":wheel,"native_elf_count":N,
            "apk_member_matches_to_installed":positive,
            "origin_classes":dict(sorted(classes.items())),
            "signed_root_independently_verified":False,
            "auditwheel_transform_verified":False,
            "license_texts_reviewed":False,"distribution":"BLOCKED",
            "ha_installation":"BLOCKED","opera_activation":"BLOCKED",
            "status":"ORIGINAL_APK_BYTES_PARTIALLY_CORRELATED_NOT_RELEASED"}
def main(argv):
    if len(argv)!=5: return 2
    try:
        docs=[]
        for name in argv[1:4]:
            p=Path(name)
            if p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<6*1024*1024:
                raise ValueError("unsafe_input")
            docs.append(json.loads(p.read_text()))
        result=assess(*docs)
        out=Path(argv[4])
        if out.is_symlink(): raise ValueError("unsafe_output")
        out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    except (ValueError,TypeError,KeyError,OSError,UnicodeError):
        print("F7 original native release gate rejected",file=sys.stderr)
        return 1
    return 0
if __name__=="__main__": raise SystemExit(main(sys.argv))
