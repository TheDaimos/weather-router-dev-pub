"""F7 CycloneDX 1.5 evidence-only native wheel BOM, standard-library only.

Uses real SHA member inventory and APK filename candidate matrix, never
guesses unknown package identities/licenses. No signed provenance or approval.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

LIMIT = 3 * 1024 * 1024
HEX = re.compile(r"[a-f0-9]{64}\Z")

def _read(path):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size > LIMIT:
        raise ValueError("input_invalid")
    with p.open("rb") as f:
        raw=f.read(LIMIT+1)
    if len(raw)>LIMIT:
        raise ValueError("input_oversize")
    return json.loads(raw)

def build(inventory, attribution):
    if (inventory.get("schema")!="weather_router.f7.native_candidate_inventory.v2"
            or inventory.get("status")!="UNAPPROVED_NOT_DISTRIBUTABLE"
            or attribution.get("schema")!="weather_router.f7.native_apk_license_candidates.v1"
            or attribution.get("status")!="UNAPPROVED_NOT_DISTRIBUTABLE"):
        raise ValueError("incorrect_evidence_schema")
    files=inventory.get("files")
    elfs=attribution.get("elf_candidates")
    if (not isinstance(files,list) or len(files)!=inventory.get("files_count")
            or not isinstance(elfs,list) or len(elfs)!=inventory.get("native_elf_count")
            or len(elfs)!=attribution.get("native_elf_count")
            or attribution.get("wheel_sha256")!=inventory.get("candidate",{}).get("sha256")):
        raise ValueError("evidence_crosscheck")
    indexed={}
    for f in files:
        name,sha=f.get("path"),f.get("sha256")
        if not isinstance(name,str) or name in indexed or not isinstance(sha,str) or not HEX.fullmatch(sha):
            raise ValueError("bad_member_hash")
        indexed[name]=f
    components=[]
    for e in elfs:
        name,sha=e.get("wheel_path"),e.get("wheel_sha256")
        if name not in indexed or indexed[name].get("elf_magic") is not True or indexed[name]["sha256"]!=sha:
            raise ValueError("native_component_not_in_wheel")
        candidates=e.get("apk_source_candidates")
        if not isinstance(candidates,list):
            raise ValueError("bad_attribution")
        props=[{"name":"weather_router:evidence","value":e.get("attribution_confidence","unresolved")},
               {"name":"weather_router:license_review","value":"REQUIRED"}]
        for c in candidates:
            props.append({"name":"weather_router:unverified_apk_candidate",
                          "value":f"{c.get('package','UNKNOWN')}@{c.get('version','UNKNOWN')} license={c.get('declared_license') or 'UNKNOWN'}"})
        components.append({"type":"file","bom-ref":"urn:sha256:"+sha+":"+name,
                           "name":name,"hashes":[{"alg":"SHA-256","content":sha}],
                           "properties":props})
    if len(set(c["name"] for c in components))!=len(components):
        raise ValueError("duplicate_native_components")
    doc={"bomFormat":"CycloneDX","specVersion":"1.5","version":1,
         "metadata":{"component":{"type":"application","name":"weather-router-f7-native-candidate-evidence",
                                  "version":"0.10.161"},
                     "properties":[
                         {"name":"weather_router:approval","value":"BLOCKED"},
                         {"name":"weather_router:binary_distributable","value":"false"},
                         {"name":"weather_router:origin_attested","value":"false"},
                         {"name":"weather_router:license_review","value":"REQUIRED"},
                         {"name":"weather_router:cve_review","value":"REQUIRED"}]},
         "components":components}
    return doc

def main(argv):
    if len(argv)!=3:
        print("usage: f7_cyclonedx_evidence.py WHEEL_INVENTORY_JSON APK_CANDIDATES_JSON",file=sys.stderr)
        return 2
    try:
        report=build(_read(argv[1]),_read(argv[2]))
    except (ValueError,OSError,UnicodeError,TypeError,AttributeError,KeyError):
        print("F7 CycloneDX evidence rejected",file=sys.stderr)
        return 1
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv))
