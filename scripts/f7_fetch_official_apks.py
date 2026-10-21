"""F7 original Alpine APK acquisition: isolated CI, version-pinned, read-only.

Never installs APKs. Captures exact downloaded APK SHA-256, official
repository URL returned by apk-tools, signature verification result and
temporary container key fingerprints. Package signature verification based on
image-bundled keys is NOT an independently attested trust root.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

PKG = re.compile(r"[A-Za-z0-9][A-Za-z0-9+_.-]{0,100}\Z")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9+_.:~-]{0,100}\Z")
MAX_PACKAGE_COUNT = 90
MAX_APK_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
TIME_BUDGET = 260

def selected(mapping):
    if (mapping.get("schema") != "weather_router.f7.native_apk_license_candidates.v1"
            or mapping.get("status") != "UNAPPROVED_NOT_DISTRIBUTABLE"):
        raise ValueError("invalid_source_mapping")
    unique={}
    for row in mapping.get("elf_candidates",[]):
        if row.get("attribution_confidence")!="filename_only_not_binary_proof":
            continue
        for cand in row.get("apk_source_candidates",[]):
            name,version=cand.get("package"),cand.get("version")
            if not isinstance(name,str) or not PKG.fullmatch(name) or not isinstance(version,str) or not VERSION.fullmatch(version):
                raise ValueError("unsafe_package_name")
            unique[(name,version)]=True
    if not 0 < len(unique) <= MAX_PACKAGE_COUNT:
        raise ValueError("invalid_package_count")
    return sorted(unique)

def _sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as fd:
        for chunk in iter(lambda:fd.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def fetch(mapping, target, *, runner=subprocess.run):
    if os.environ.get("GITHUB_ACTIONS")!="true" or os.environ.get("WR_OPERA_ISOLATED_CI")!="1" or not Path("/etc/alpine-release").is_file():
        raise ValueError("not_disposable_alpine_ci")
    target=Path(target)
    if target != Path("/wheelhouse/apk-originals") or target.is_symlink():
        raise ValueError("nonfixed_apk_destination")
    target.mkdir(mode=0o700,parents=True,exist_ok=True)
    if shutil.disk_usage(target).free < MAX_TOTAL_BYTES:
        raise ValueError("not_enough_wheelhouse_space")
    keys={}
    for p in Path("/etc/apk/keys").glob("*.pub"):
        if p.is_file() and not p.is_symlink() and p.stat().st_size < 16000:
            keys[p.name]=_sha(p)
    packages=selected(mapping)
    # apk-tools 3 fetch resolves package names, not exact-version constraints.
    # Refresh signed indexes and REQUIRE the exact installed filename below.
    # Never install a package.
    refresh=runner(["apk","update"],capture_output=True,text=True,timeout=35,check=False)
    index_available=refresh.returncode==0
    cutoff=time.monotonic()+TIME_BUDGET
    results=[]
    for name,version in packages:
        target_file=target/f"{name}-{version}.apk"
        data={"name":name,"version":version,"declared_license":None,
              "repo_url":None,"archive_sha256":None,"archive_bytes":None,
              "apk_verify_result":"NOT_VERIFIED",
              "trust_anchor_independently_verified":False,
              "status":"NOT_FETCHED"}
        if not index_available:
            data["status"]="OFFICIAL_INDEX_REFRESH_FAILED"
            results.append(data)
            continue
        if time.monotonic() > cutoff:
            data["status"]="TIME_BUDGET_EXHAUSTED"
            results.append(data)
            continue
        try:
            reference=name
            # Alpine's own verified index and repository client; never use
            # --allow-untrusted and never invoke apk add/install.
            url=runner(["apk","fetch","--url",reference],
                       capture_output=True,text=True,timeout=15,check=False)
            if url.returncode==0:
                valid=[x.strip() for x in url.stdout.splitlines() if x.strip().startswith("https://")]
                if len(valid)==1 and valid[0].endswith("/"+target_file.name) and "alpinelinux.org/" in valid[0]:
                    data["repo_url"]=valid[0]
            result=runner(["apk","fetch","--output",str(target),reference],
                          capture_output=True,text=True,timeout=35,check=False)
            if result.returncode:
                data["status"]="OFFICIAL_APK_FETCH_FAILED"
            elif (target_file.is_file() and not target_file.is_symlink()
                  and 0 < target_file.stat().st_size <= MAX_APK_BYTES):
                data["archive_sha256"]=_sha(target_file)
                data["archive_bytes"]=target_file.stat().st_size
                verified=runner(["apk","verify",str(target_file)],
                                capture_output=True,text=True,timeout=30,check=False)
                data["apk_verify_result"]=("VALID_AGAINST_CI_CONTAINER_KEYS" if verified.returncode==0
                                           else "SIGNATURE_OR_CONTENT_VERIFICATION_FAILED")
                data["status"]=("INDEXED_AND_SIGNED_BY_CI_KEYS_NOT_INDEPENDENTLY_ATTESTED"
                                if verified.returncode==0 else "NOT_AUTHENTICATED")
            else:
                observed=sorted(p.name for p in target.glob(name+"-*.apk") if p.is_file())
                data["status"]="EXACT_VERSION_NOT_IN_SIGNED_OFFICIAL_INDEX" if observed else "MISSING_OR_OVERSIZE_APK_ARCHIVE"
                data["observed_archive_names"]=observed[:8]
        except (OSError,subprocess.TimeoutExpired):
            data["status"]="FETCH_OR_VERIFICATION_UNAVAILABLE"
        results.append(data)
    return {
        "schema":"weather_router.f7.official_apk_archive_candidates.v1",
        "status":"CI_INDEX_AND_KEY_CHECK_NOT_INDEPENDENT_PROVENANCE",
        "wheel_sha256":mapping.get("wheel_sha256"),
        "alpine_ci_key_file_sha256":keys,
        "official_index_refresh_success":index_available,
        "package_requested_count":len(packages),
        "apk_fetched_count":sum(x["archive_sha256"] is not None for x in results),
        "apk_signature_verified_using_ci_keys_count":sum(x["apk_verify_result"]=="VALID_AGAINST_CI_CONTAINER_KEYS" for x in results),
        "total_archive_bytes":sum(x["archive_bytes"] or 0 for x in results),
        "packages":results,
        "apk_mirrors_trust_independently_attested":False,
        "repository_key_trust_independently_attested":False,
        "license_review":"REQUIRED",
        "binary_distribution":"BLOCKED","ha_installation":"BLOCKED","opera_activation":"BLOCKED"
    }

def main(argv):
    if len(argv)!=3:
        print("usage: f7_fetch_official_apks.py MAPPING.json REPORT.json",file=sys.stderr)
        return 2
    try:
        mapping=json.loads(Path(argv[1]).read_text())
        report=fetch(mapping,Path("/wheelhouse/apk-originals"))
        Path(argv[2]).write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    except (ValueError,OSError,TypeError,KeyError):
        print("F7 archive provenance attempt failed closed",file=sys.stderr)
        return 1
    print("F7 OFFICIAL ALPINE APK ARCHIVES:",report["apk_fetched_count"],"/",
          report["package_requested_count"],"downloaded,",
          report["apk_signature_verified_using_ci_keys_count"],
          "validated with CI image keys, independent key provenance NOT verified")
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv))
