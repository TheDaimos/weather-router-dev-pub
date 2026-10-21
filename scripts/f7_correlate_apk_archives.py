"""F7: correlate bytes from Alpine CI-key-verified APKs to native ELF origins.

Strictly read-only (tarfile in memory, no extraction). Three separate SHA
relationships: APK archive SHA, APK member ELF SHA, installed ELF SHA, and
repaired Wheel ELF SHA. Never equate nonidentical binaries, never infer license
clearance or independent key authenticity from apk verify alone.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile

HEX = re.compile(r"[0-9a-f]{64}\Z")
MAX_APK_BYTES = 100 * 1024 * 1024
MAX_ELF_BYTES = 64 * 1024 * 1024
MAX_TOTAL_MEMBER_BYTES = 500 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20000

def _sha(data):
    return hashlib.sha256(data).hexdigest()

def _candidates(archive, filenames):
    """Only decompress candidate .so regular members; no links/extract."""
    found = []
    total, count = 0, 0
    with tarfile.open(archive, "r|gz") as tar:
        for info in tar:
            count += 1
            if count > MAX_ARCHIVE_MEMBERS:
                raise ValueError("apk_member_limit")
            if not info.isfile():
                continue
            total += info.size
            if info.size < 0 or total > MAX_TOTAL_MEMBER_BYTES:
                raise ValueError("apk_decompression_limit")
            name=info.name.removeprefix("./")
            if not name.startswith(("usr/lib/", "lib/")):
                continue
            if Path(name).name not in filenames or not 0 < info.size <= MAX_ELF_BYTES:
                continue
            handle=tar.extractfile(info)
            if handle is None:
                continue
            raw=handle.read(MAX_ELF_BYTES+1)
            if len(raw)!=info.size or not raw.startswith(b"\x7fELF"):
                continue
            found.append({"archive_elf_path":name,
                          "sha256":_sha(raw),"bytes":len(raw)})
    return found

def correlate(binary, apks, root):
    if (binary.get("schema")!="weather_router.f7.apk_embedded_binary_comparison.v1"
            or apks.get("schema")!="weather_router.f7.official_apk_archive_candidates.v1"
            or binary.get("wheel_sha256")!=apks.get("wheel_sha256")
            or binary.get("native_elf_count")!=101):
        raise ValueError("invalid_evidence_contract")
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("invalid_archive_root")
    index={(x["name"],x["version"]):x for x in apks.get("packages",[])}
    if len(index)!=len(apks.get("packages",[])):
        raise ValueError("duplicate_apk_records")
    sha_cache={}
    rows=[]
    for row in binary.get("elf_components",[]):
        name=row["wheel_path"]
        original_sha=row.get("original_installed_sha256")
        original_path=row.get("original_installed_path")
        # The physical shared object may be a versioned target of a symlink.
        resolved=row.get("original_resolved_path")
        names={Path(x).name for x in (original_path,resolved)
               if isinstance(x,str) and x}
        verified=[]
        candidates=row.get("candidates",[])
        for candidate in candidates:
            key=(candidate["name"],candidate["version"])
            pkg=index.get(key)
            if pkg is None or pkg.get("apk_verify_result")!="VALID_AGAINST_CI_CONTAINER_KEYS":
                continue
            if not (candidate.get("installed_db_owns_original") is True
                    and isinstance(original_sha,str) and HEX.fullmatch(original_sha)
                    and isinstance(pkg.get("archive_sha256"),str) and HEX.fullmatch(pkg["archive_sha256"])):
                continue
            filename=f"{key[0]}-{key[1]}.apk"
            path=root/filename
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_APK_BYTES:
                continue
            raw=path.read_bytes()
            if _sha(raw)!=pkg["archive_sha256"]:
                raise ValueError("archive_bytes_mismatch")
            if key not in sha_cache:
                sha_cache[key]=_candidates(path, names)
            found=[e for e in sha_cache[key] if e["sha256"]==original_sha]
            if found:
                verified.append({"apk_package":key[0],"apk_version":key[1],
                                 "apk_sha256":pkg["archive_sha256"],
                                 "apk_elf_sha256":original_sha,
                                 "apk_elf_file":found[0]["archive_elf_path"],
                                 "signed_by_pinned_ci_alpine_keys":True,
                                 "external_key_attestation":False,
                                 "wheel_identical_to_signed_apk_elf":
                                     row.get("wheel_sha256")==original_sha})
        if verified:
            status=("SIGNED_APK_MEMBER_EQUALS_WHEEL_ELF_KEY_NOT_INDEPENDENT"
                    if any(x["wheel_identical_to_signed_apk_elf"] for x in verified)
                    else "SIGNED_APK_MEMBER_EQUALS_INSTALLED_NOT_REPAIRED_ELF")
        elif name.startswith("rasterio/"):
            status="RASTERIO_SOURCE_WHEEL_NO_ALPINE_APK"
        else:
            status="APK_BINARY_OR_SIGNATURE_NOT_VERIFIED"
        rows.append({"wheel_path":name,"original_installed_sha256":original_sha,
                     "wheel_sha256":row.get("wheel_sha256"),
                     "status":status,"signed_archive_matches":verified,
                     "auditwheel_transformation_reproduced_from_apk":False,
                     "independent_key_trust":False,
                     "license_review":"REQUIRED"})
    if len(rows)!=101:
        raise ValueError("native_component_incomplete")
    return {
        "schema":"weather_router.f7.apk_signed_member_correlation.v1",
        "status":"CI_SIGNED_INDEX_ROOT_NOT_INDEPENDENTLY_ATTESTED",
        "wheel_sha256":binary["wheel_sha256"],
        "native_elf_count":101,
        "archive_elf_matches_installed_count":sum(bool(x["signed_archive_matches"]) for x in rows),
        "archive_elf_matches_repaired_wheel_count":sum(
            any(y["wheel_identical_to_signed_apk_elf"] for y in x["signed_archive_matches"]) for x in rows),
        "apk_signatures_checked_against_container_keys":True,
        "independent_root_of_trust":False,
        "auditwheel_change_chain_verified":False,
        "license_review":"REQUIRED","ha_installation":"BLOCKED",
        "opera_activation":"BLOCKED","elf_components":rows,
    }

def main(args):
    if len(args)!=5:
        print("usage: f7_correlate_apk_archives.py BINARY.json OFFICIAL_APKS.json APK_DIR OUTPUT.json",file=sys.stderr)
        return 2
    try:
        import os
        if os.environ.get("GITHUB_ACTIONS")!="true" or os.environ.get("WR_OPERA_ISOLATED_CI")!="1":
            raise ValueError("CI_only")
        result=correlate(json.loads(Path(args[1]).read_text()),
                         json.loads(Path(args[2]).read_text()),args[3])
        Path(args[4]).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    except (ValueError,KeyError,TypeError,OSError,tarfile.TarError):
        print("F7 Alpine signed archive ELF correlation rejected",file=sys.stderr)
        return 1
    print("F7 VERIFIED APK ARCHIVE MEMBER BYTES:",result["archive_elf_matches_installed_count"],
          "installed, ",result["archive_elf_matches_repaired_wheel_count"],
          "repaired wheel, 101 total; no independent signature root or license grant")
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv))
