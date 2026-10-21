"""F7-L08: read-only official Alpine EDGE cross-branch OpenSSL archive probe.

Different release channel is not the original v3.24 package. Identical file
name/version NEVER proves identical bytes. This explicitly tests actual bytes
against known installed ELF while keeping native distribution blocked.
"""
from __future__ import annotations
import hashlib, io, json, os, pathlib, ssl, subprocess, sys, tarfile
import urllib.request
from urllib.parse import urlparse
from f7_apk_multi_gzip import open_apk_tar_segments, UnsafeApkArchive

BASE="https://dl-cdn.alpinelinux.org/alpine/edge/main/x86_64/"
ITEMS={"libcrypto3":("libcrypto.so.3","3.5.8-r0"),"libssl3":("libssl.so.3","3.5.8-r0")}
MAX_BYTES=12*1024*1024

def digest(content):return hashlib.sha256(content).hexdigest()

def compare(original_report):
    rows=original_report["elf_components"]
    selected={}
    for name,(soname,version) in ITEMS.items():
        matches=[r for r in rows if r.get("original_resolved_path")=="usr/lib/"+soname]
        if len(matches)!=1:raise ValueError("ambiguous_reference_elf_"+name)
        selected[name]=(version,soname,matches[0]["original_installed_sha256"])
    results=[]
    for name,(version,soname,expected) in selected.items():
        url=BASE+name+"-"+version+".apk"
        item={"name":name,"version":version,"channel":"edge_not_v3.24",
              "url":url,"original_installed_elf_sha256":expected,
              "apk_sha256":None,"package_signature_verified_in_ci":False,
              "extracted_elf_sha256":None,"byte_identical_to_installed_original":False,
              "status":"NOT_AVAILABLE"}
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"WeatherRouter-F7-ReadOnly-CI/1"})
            with urllib.request.urlopen(req,timeout=14,context=ssl.create_default_context()) as response:
                if response.status!=200 or response.geturl()!=url:
                    raise ValueError("redirect_or_non_200")
                data=response.read(MAX_BYTES+1)
            if not 0<len(data)<=MAX_BYTES:raise ValueError("archive_size")
            # Isolated volatile folder, never part of HA or published artifact.
            p=pathlib.Path("/wheelhouse/f7-openssl-cross-branch")/(name+"-"+version+".apk")
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(data)
            item["apk_sha256"]=digest(data)
            verify=subprocess.run(["apk","verify",str(p)],capture_output=True,timeout=30,check=False)
            if verify.returncode:
                item["status"]="APK_VERIFY_FAILED_CI_KEYS"
            else:
                item["package_signature_verified_in_ci"]=True
                try:
                    segments=open_apk_tar_segments(p)
                    candidates=[]
                    for segment in segments:
                        with tarfile.open(fileobj=segment,mode="r:") as t:
                            for m in t:
                                if m.isfile() and m.name.lstrip("./")=="usr/lib/"+soname:
                                    f=t.extractfile(m)
                                    if f is not None and m.size<=MAX_BYTES:
                                        candidates.append(digest(f.read(MAX_BYTES+1)))
                    if len(candidates)==1:
                        item["extracted_elf_sha256"]=candidates[0]
                        item["byte_identical_to_installed_original"]=(candidates[0]==expected)
                        item["status"]="CROSS_BRANCH_ELF_IDENTICAL_CI_KEYS_ONLY" if candidates[0]==expected else "CROSS_BRANCH_ELF_DIFFERENT"
                    else:item["status"]="ELF_MEMBER_MISSING_OR_AMBIGUOUS"
                except (UnsafeApkArchive,tarfile.TarError,OSError):
                    item["status"]="V3_OR_UNSUPPORTED_APK_FORMAT_NO_ELF_READ"
        except (OSError,ValueError,TimeoutError,urllib.error.URLError,subprocess.TimeoutExpired) as exc:
            item["status"]="UNAVAILABLE_OR_UNTRUSTED_"+type(exc).__name__
        results.append(item)
    return {"schema":"weather_router.f7.openssl_official_edge_cross_branch_probe.v1",
            "results":results,"v3_24_original_proven":False,
            "independent_signing_key_provenance":False,
            "distribution":"BLOCKED","ha_installation":"BLOCKED"}

if __name__=="__main__":
    if (len(sys.argv)!=3 or os.getenv("GITHUB_ACTIONS")!="true"
        or os.getenv("WR_OPERA_ISOLATED_CI")!="1" or not pathlib.Path("/etc/alpine-release").exists()):
        raise SystemExit(2)
    data=json.loads(pathlib.Path(sys.argv[1]).read_text())
    out=compare(data)
    pathlib.Path(sys.argv[2]).write_text(json.dumps(out,sort_keys=True,indent=2)+"\n")
    for item in out["results"]:print("F7 OPENSSL OFFICIAL CROSS BRANCH:",item["name"],item["status"])
