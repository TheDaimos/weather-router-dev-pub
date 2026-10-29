"""F7: CycloneDX 1.5 candidate SBOM from real ELF and APK audit JSON.

Every embedded ELF object is retained as a file component (including unknown
owners). APK filename matching is not silently promoted to verified provenance.
No vulnerability scan, license clearance, distribution, or native runtime.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys

MAX_JSON=2*1024*1024
DIGEST=re.compile(r"[0-9a-f]{64}\Z")

def _read(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<=MAX_JSON:
        raise ValueError("invalid_source_file")
    with p.open("rb") as f:
        raw=f.read(MAX_JSON+1)
    if len(raw)>MAX_JSON:
        raise ValueError("oversize_source")
    return json.loads(raw)

def _property(name,value):
    return {"name":"weather-router:f7:"+name,"value":str(value)}

def produce(inventory, mapping):
    if (not isinstance(inventory,dict) or not isinstance(mapping,dict)
            or inventory.get("schema")!="weather_router.f7.native_candidate_inventory.v2"
            or mapping.get("schema")!="weather_router.f7.native_apk_license_candidates.v1"
            or inventory.get("status")!="UNAPPROVED_NOT_DISTRIBUTABLE"
            or mapping.get("status")!="UNAPPROVED_NOT_DISTRIBUTABLE"):
        raise ValueError("unapproved_inventory_required")
    sha=inventory.get("candidate",{}).get("sha256")
    if (not isinstance(sha,str) or not DIGEST.fullmatch(sha)
            or sha!=mapping.get("wheel_sha256")):
        raise ValueError("cross_inventory_sha_mismatch")
    files=inventory.get("files")
    elf= [x for x in files if x.get("elf_magic")] if isinstance(files,list) else []
    linked=mapping.get("elf_candidates")
    if (len(elf)!=inventory.get("native_elf_count")
            or len(elf)!=mapping.get("native_elf_count")
            or not isinstance(linked,list) or len(linked)!=len(elf)):
        raise ValueError("incomplete_elf_inventory")
    bypath={}
    for x in elf:
        path=x.get("path"); digest=x.get("sha256")
        if (not isinstance(path,str) or path in bypath
                or not isinstance(digest,str) or DIGEST.fullmatch(digest) is None
                or type(x.get("size_bytes")) is not int):
            raise ValueError("invalid_elf_record")
        bypath[path]=x
    bymap={}
    for x in linked:
        path=x.get("wheel_path")
        if not isinstance(path,str) or path in bymap:
            raise ValueError("duplicate_license_record")
        bymap[path]=x
    if set(bydel for bydel in bymap)!=set(bypath):
        raise ValueError("missing_license_record")
    components=[]
    unverified=0
    for i,path in enumerate(sorted(bypath)):
        row=bypath[path]; audit=bymap[path]
        if audit.get("wheel_sha256")!=row["sha256"]:
            raise ValueError("independent_file_hash_mismatch")
        candidates=audit.get("apk_source_candidates")
        if not isinstance(candidates,list):
            raise ValueError("invalid_source_candidates")
        confidence=audit.get("attribution_confidence")
        if confidence not in ("filename_only_not_binary_proof",
                              "wheel_metadata_not_transitive_binary_license","unresolved"):
            raise ValueError("invalid_confidence")
        unverified+=1
        licenses=sorted({x["declared_license"] for x in candidates
                        if isinstance(x,dict) and isinstance(x.get("declared_license"),str)
                        and x["declared_license"]})
        comp={"type":"file","bom-ref":f"f7-elf-{i:03d}",
              "name":path,
              "hashes":[{"alg":"SHA-256","content":row["sha256"]}],
              "properties":[
                  _property("attribution_confidence",confidence),
                  _property("binary_source_hash_confirmed","false"),
                  _property("license_obligations_review","REQUIRED"),
                  _property("size_bytes",row["size_bytes"]),
                  _property("needs",";".join(row.get("needed",[]))),
                  _property("source_candidates",";".join(
                      str(p.get("package"))+"@"+str(p.get("version"))
                      for p in candidates if isinstance(p,dict))),
              ]}
        if licenses:
            # Only the APK *declaration* is available, so use a free-form
            # name, never a claim of SPDX-ID clearance.
            comp["licenses"]=[{"license":{"name":name}} for name in licenses]
        components.append(comp)
    cd={
        "bomFormat":"CycloneDX","specVersion":"1.5","version":1,
        "metadata":{"component":{"type":"application","name":"WeatherRouter-F7-unapproved-native-candidate",
                                 "version":"0.10.161"}},
        "components":components,
        "properties":[_property("artifact_state","UNAPPROVED_NOT_DISTRIBUTABLE"),
                      _property("wheel_sha256",sha),
                      _property("all_elf_origin_unverified","true"),
                      _property("security_scan","NOT_PERFORMED"),
                      _property("license_review","REQUIRED"),
                      _property("ha_installation","BLOCKED"),
                      _property("opera_activation","BLOCKED")]
    }
    quality={
        "schema":"weather_router.f7.sbom_quality.v1",
        "status":"EVIDENCE_ONLY_NOT_LICENSE_CLEARED",
        "wheel_sha256":sha,
        "elf_expected":inventory["native_elf_count"],
        "elf_included":len(components),
        "elf_unverified_origin":unverified,
        "name_only_matches":sum(
            x["attribution_confidence"]=="filename_only_not_binary_proof"
            for x in linked),
        "rasterio_internal_metadata_only":sum(
            x["attribution_confidence"]=="wheel_metadata_not_transitive_binary_license"
            for x in linked),
        "unknown_components":sorted(
            x["wheel_path"] for x in linked if x["attribution_confidence"]=="unresolved"),
        "license_obligations_review":"REQUIRED",
        "cve_scan":"REQUIRED","signed_provenance":False,
        "full_safety_and_license_approval":False,
        "ha_installation":"BLOCKED"}
    return cd,quality

def main(argv):
    if len(argv)!=5:
        print("usage: f7_generate_sbom.py INVENTORY LICENSE_AUDIT BOM_OUT QUALITY_OUT",file=sys.stderr)
        return 2
    try:
        bom,quality=produce(_read(argv[1]),_read(argv[2]))
        for filename,doc in ((argv[3],bom),(argv[4],quality)):
            p=Path(filename)
            if p.is_symlink() or (p.exists() and not p.is_file()):
                raise ValueError("invalid_output")
            p.write_text(json.dumps(doc,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    except (ValueError,OSError,TypeError,KeyError):
        print("F7 SBOM quality assessment rejected",file=sys.stderr)
        return 1
    print("F7 CycloneDX candidate emitted; license and security approval BLOCKED")
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv))
