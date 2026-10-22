"""F7 Alpine security database candidate check: offline, no network.

Inputs must be downloaded from the official Alpine secdb and SHA-recorded
separately. Installed build APKs are NOT identical to embedded Wheel components.
No absence of CVEs in this report certifies the native Wheel as safe.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

MAX=8*1024*1024
HEX=re.compile(r"[a-f0-9]{64}\Z")
PKG=re.compile(r"[a-z0-9][a-z0-9+_.-]{0,120}\Z")
VERSION=re.compile(r"[a-zA-Z0-9][a-zA-Z0-9+_.:~=-]{0,120}\Z")

def _source(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<=MAX:
        raise ValueError("unreadable_feed_or_snapshot")
    data=p.read_bytes()
    return json.loads(data),hashlib.sha256(data).hexdigest()

def apk_compare(installed,fixed):
    if not VERSION.fullmatch(installed) or not VERSION.fullmatch(fixed):
        raise ValueError("invalid_alpine_version")
    result=subprocess.run(["apk","version","-t",installed,fixed],
                          stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,timeout=4,check=False)
    if result.returncode or result.stdout.strip() not in (b"<",b"=",b">"):
        raise ValueError("apk_version_comparison_failed")
    return result.stdout.decode().strip()

def assess(snapshot,feeds,*,compare=apk_compare):
    if (snapshot.get("schema")!="weather_router.f7.build_input_snapshot.v1"
            or snapshot.get("status")!="EVIDENCE_ONLY_NOT_REPRODUCIBLE"
            or not isinstance(snapshot.get("apk_packages"),list)):
        raise ValueError("invalid_build_snapshot")
    fixed={}
    for feed in feeds:
        if not isinstance(feed,dict) or not isinstance(feed.get("packages"),list):
            raise ValueError("unsupported_alpine_secdb")
        if feed.get("distroversion")!="v3.24" or feed.get("reponame") not in ("main","community"):
            raise ValueError("wrong_secdb_release_or_repo")
        for row in feed["packages"]:
            p=row.get("pkg",{})
            name=p.get("name")
            fixes=p.get("secfixes",{})
            if not isinstance(name,str) or not PKG.fullmatch(name) or not isinstance(fixes,dict):
                raise ValueError("invalid_secdb_package")
            fixed.setdefault(name,{}).update(fixes)
    out=[]
    looked_up=set()
    for x in snapshot["apk_packages"]:
        name=x.get("name");version=x.get("version"); origin=x.get("origin")
        if not isinstance(name,str) or not PKG.fullmatch(name) or not isinstance(version,str) or not VERSION.fullmatch(version):
            raise ValueError("invalid_apk_candidate")
        targets=[x for x in (name,origin) if isinstance(x,str) and x in fixed]
        findings=[]
        comparisons=0
        for target in dict.fromkeys(targets):
            for fixed_version,cves in fixed[target].items():
                if not isinstance(cves,list) or not VERSION.fullmatch(fixed_version):
                    raise ValueError("invalid_fixed_version")
                relation=compare(version,fixed_version)
                if relation not in ("<","=",">"):
                    raise ValueError("invalid_version_result")
                comparisons+=1
                if comparisons>500:
                    raise ValueError("too_many_fix_comparisons")
                if relation=="<":
                    findings.extend({"advisory":str(v),"fixed_in":fixed_version,
                                     "secdb_package":target,
                                     "classification":"POTENTIALLY_UNFIXED_VERSION"}
                                    for v in cves if isinstance(v,str))
        out.append({"apk_name":name,"installed_version":version,
                    "source_origin":origin,
                    "feed_matches":list(dict.fromkeys(targets)),
                    "potential_advisory_candidates":findings,
                    "assessment":"POSSIBLE_UNFIXED_ADVISORIES" if findings else
                    "NO_LISTED_UNFIXED_FIXES_NOT_A_CLEARANCE" if targets else
                    "UNKNOWN_NOT_IN_FEED"})
    return {
        "schema":"weather_router.f7.alpine_secdb_candidates.v1",
        "status":"DIAGNOSTIC_ONLY_NOT_SECURITY_CLEARED",
        "apk_scanned":len(out),
        "packages_with_possible_findings":sum(bool(x["potential_advisory_candidates"]) for x in out),
        "packages_without_feed_match":sum(x["assessment"]=="UNKNOWN_NOT_IN_FEED" for x in out),
        "every_embedded_elf_mapped_to_installed_apk":False,
        "scan_claims_all_vulnerabilities":False,
        "fixed_versions_independently_attested":False,
        "licenses_cleared":False,
        "vulnerability_review":"REQUIRED",
        "ha_installation":"BLOCKED","opera_activation":"BLOCKED",
        "packages":out,
    }

def main(argv):
    if len(argv)!=5:
        print("usage: f7_alpine_secdb_candidates.py BUILD_INPUTS MAIN_JSON COMMUNITY_JSON OUTPUT_JSON",file=sys.stderr)
        return 2
    try:
        snap,_=_source(argv[1])
        main,sha_main=_source(argv[2])
        comm,sha_comm=_source(argv[3])
        result=assess(snap,[main,comm])
        result["feed_sha256"]={"v3.24/main":sha_main,"v3.24/community":sha_comm}
        dst=Path(argv[4])
        if dst.is_symlink():raise ValueError("unsafe_output")
        dst.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    except (ValueError,OSError,TypeError,KeyError,subprocess.TimeoutExpired):
        print("F7 Alpine security feed diagnostic incomplete or rejected",file=sys.stderr)
        return 1
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv))
