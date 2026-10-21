"""F7: original Alpine-installed ELF bytes vs auditwheel-repaired ELF bytes.

CI-only diagnostic; compares ACTUAL bytes, never names as proof. Original APK
archives (if fetched) are hashed separately; no signature/redistribution claim.
Never imports a wheel, loads native code, installs packages or touches HA.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
from zipfile import ZipFile, BadZipFile

HEX = re.compile(r"[0-9a-f]{64}\Z")
SONAME_HASH = re.compile(r"-[0-9a-f]{8}(?=\.)")
MAX_JSON = 3 * 1024 * 1024
MAX_ELF = 64 * 1024 * 1024
MAX_WHEEL = 110 * 1024 * 1024
MAX_APK = 100 * 1024 * 1024

def sha(data):
    return hashlib.sha256(data).hexdigest()

def load_json(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= MAX_JSON:
        raise ValueError("invalid_report")
    return json.loads(p.read_bytes())

def _installed_owners(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("invalid_installed_database")
    owners = {}
    for block in p.read_text().split("\n\n"):
        info, names, folder = {}, [], ""
        for line in block.splitlines():
            if len(line) < 2 or line[1] != ":":
                continue
            k, v = line[0], line[2:]
            if k in ("P", "V", "L", "o"):
                info.setdefault(k, v)
            elif k == "F":
                folder = v.lstrip("/")
            elif k == "R":
                names.append(f"{folder}/{v}" if folder else v)
        if info.get("P") and info.get("V"):
            record = {"name":info["P"], "version":info["V"],
                      "origin":info.get("o"), "declared_license":info.get("L")}
            for name in names:
                owners.setdefault(name, []).append(record)
    return owners

def _read_original(root, filename):
    # The installed DB is an index, not proof. Only these native system folders.
    for folder in ("usr/lib", "lib"):
        p = root / folder / filename
        if not p.is_file():
            continue
        target = p.resolve()
        if not (target.is_file() and
                any(target.is_relative_to((root / x).resolve())
                    for x in ("usr/lib", "lib"))):
            continue
        if target.stat().st_size > MAX_ELF:
            continue
        return (str(p.relative_to(root)), p.read_bytes())
    return None

def compare(inv, attribution, db, wheel, *, source_root="/", archive_dir=None):
    if (inv.get("schema") != "weather_router.f7.native_candidate_inventory.v2"
            or inv.get("status") != "UNAPPROVED_NOT_DISTRIBUTABLE"
            or attribution.get("schema") != "weather_router.f7.native_apk_license_candidates.v1"):
        raise ValueError("invalid_candidate_schema")
    wheelsha=inv.get("candidate",{}).get("sha256")
    if not isinstance(wheelsha,str) or not HEX.fullmatch(wheelsha) or attribution.get("wheel_sha256") != wheelsha:
        raise ValueError("wheel_evidence_mismatch")
    wheel=Path(wheel)
    if wheel.is_symlink() or not wheel.is_file() or not 0 < wheel.stat().st_size <= MAX_WHEEL:
        raise ValueError("invalid_wheel")
    if sha(wheel.read_bytes()) != wheelsha:
        raise ValueError("wheel_bytes_mismatch")
    rows=attribution.get("elf_candidates")
    if not isinstance(rows,list) or len(rows) != inv.get("native_elf_count") or len(rows) != 101:
        raise ValueError("incomplete_attribution")
    members={e["path"]:e for e in inv.get("files",[]) if e.get("elf_magic") is True}
    if len(members)!=101 or set(members)!={e.get("wheel_path") for e in rows}:
        raise ValueError("invalid_native_member_index")
    owners = _installed_owners(db)
    root = Path(source_root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("invalid_source_root")
    archive_path = Path(archive_dir) if archive_dir is not None else None
    archives={}
    if archive_path is not None:
        if archive_path.is_symlink() or not archive_path.is_dir():
            raise ValueError("invalid_archive_dir")
        for f in archive_path.iterdir():
            if (f.name.endswith(".apk") and not f.is_symlink() and
                    f.is_file() and 0 < f.stat().st_size <= MAX_APK):
                archives[f.name] = {"sha256":sha(f.read_bytes()),"bytes":f.stat().st_size}
    out=[]
    with ZipFile(wheel) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError("duplicate_wheel_members")
        for evidence in sorted(rows,key=lambda x:x["wheel_path"]):
            name=evidence["wheel_path"]
            entry=members[name]
            if entry.get("sha256")!=evidence.get("wheel_sha256") or not HEX.fullmatch(entry["sha256"]):
                raise ValueError("member_evidence_mismatch")
            item=z.getinfo(name)
            if item.file_size <= 0 or item.file_size > MAX_ELF:
                raise ValueError("native_elf_too_large")
            embedded=z.read(name)
            if sha(embedded)!=entry["sha256"] or not embedded.startswith(b"\x7fELF"):
                raise ValueError("embedded_elf_mismatch")
            original_name=SONAME_HASH.sub("",Path(name).name)
            candidates=evidence.get("apk_source_candidates",[])
            actual=_read_original(root,original_name) if name.startswith("rasterio.libs/") else None
            original_path, original=(actual if actual else (None,None))
            apkmatches=[]
            for pkg in candidates:
                pkgname=pkg.get("package")
                version=pkg.get("version")
                if not (isinstance(pkgname,str) and isinstance(version,str)):
                    continue
                # Package ownership must be derived from installed DB path, not
                # from the candidate's filename or license metadata alone.
                owned=bool(original_path and any(
                    x["name"]==pkgname and x["version"]==version
                    for x in owners.get(original_path, [])))
                archive_key=f"{pkgname}-{version}.apk"
                apk=archives.get(archive_key)
                apkmatches.append({"name":pkgname,"version":version,
                                   "origin":pkg.get("origin"),
                                   "declared_license":pkg.get("declared_license"),
                                   "installed_db_owns_original":owned,
                                   "official_repository_apk_archive_sha256":apk["sha256"] if apk else None,
                                   "apk_archive_bytes":apk["bytes"] if apk else None,
                                   "apk_index_signature_independently_verified":False,
                                   "apk_content_binary_match_verified":False})
            same=original is not None and original==embedded
            # This probe does not claim auditwheel transformed these bytes
            # in a verified way merely because both are valid ELF objects.
            out.append({
                "wheel_path":name,"wheel_sha256":entry["sha256"],
                "original_installed_path":original_path,
                "original_installed_sha256":sha(original) if original else None,
                "original_installed_bytes":len(original) if original else None,
                "wheel_elf_bytes":len(embedded),
                "byte_identical_to_installed_elf":bool(same),
                "origin_class":("INSTALLED_ELF_BYTE_IDENTICAL_APK_UNATTESTED" if same and any(x["installed_db_owns_original"] for x in apkmatches)
                               else "INSTALLED_ELF_DIFFERENT_TRANSFORMATION_UNVERIFIED" if original is not None
                               else "RASTERIO_SOURCE_BUILD_NEEDS_SDIST_PROVENANCE" if name.startswith("rasterio/")
                               else "INSTALLED_SOURCE_NOT_FOUND"),
                "auditwheel_renamed_soname":original_name!=Path(name).name,
                "auditwheel_transform_independently_verified":False,
                "candidates":apkmatches,"license_review":"REQUIRED"})
    direct=sum(x["origin_class"]=="INSTALLED_ELF_BYTE_IDENTICAL_APK_UNATTESTED" for x in out)
    return {
        "schema":"weather_router.f7.apk_embedded_binary_comparison.v1",
        "status":"ORIGINAL_INSTALLED_BYTES_MEASURED_NOT_SIGNED_PROVENANCE",
        "wheel_sha256":wheelsha,"native_elf_count":len(out),
        "installed_elf_byte_identical_count":direct,
        "installed_elf_different_or_unlocated_count":len(out)-direct,
        "apk_archive_sha256_count":len(archives),
        "unapproved_apk_archive_digests":archives,
        "alpine_installed_database_signed":False,
        "apk_archive_content_chain_verified":False,
        "auditwheel_transformation_verified":False,
        "license_and_security_review":"REQUIRED",
        "ha_installation":"BLOCKED","opera_activation":"BLOCKED",
        "elf_components":out,
    }

def main(args):
    if len(args) not in (6,7):
        print("usage: f7_compare_installed_elf.py INVENTORY MAPPING INSTALLED_DB WHEEL OUTPUT [APK_ARCHIVE_DIR]",file=sys.stderr)
        return 2
    try:
        # Never probe host/HA; only the *disposable Alpine build container*.
        if os.environ.get("GITHUB_ACTIONS")!="true" or os.environ.get("WR_OPERA_ISOLATED_CI")!="1":
            raise ValueError("CI_only")
        out=compare(load_json(args[1]),load_json(args[2]),args[3],args[4],
                    archive_dir=args[6] if len(args)==7 else None)
        Path(args[5]).write_text(json.dumps(out,sort_keys=True,indent=2)+"\n")
    except (ValueError,KeyError,TypeError,OSError,UnicodeError,BadZipFile):
        print("F7 native original ELF proof rejected",file=sys.stderr)
        return 1
    print("F7 ACTUAL INSTALLED ELF BYTES:",out["installed_elf_byte_identical_count"],
          "directly matched of",out["native_elf_count"],"without independent APK/provenance clearance")
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv))
