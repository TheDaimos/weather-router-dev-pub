"""F7-L12: correlate ACTUAL isolated copy/patchelf events with archived ELF hashes.
No synthetic operations, no approval, no binary release; missing stages remain visible.
"""
import json
from collections import Counter
from pathlib import Path
import sys

def read_jsonl(path, limit):
    rows=[json.loads(line) for line in Path(path).read_text().splitlines()]
    if len(rows)>limit: raise ValueError("trace_limit")
    return rows

def correlate(copies, patches, replay):
    targets=replay["elf_components"]
    if len(targets)!=101 or not replay["identical_repaired_bytes"] or replay["identical_elf_members"]!=101:
        raise ValueError("replay_not_reproducible")
    result=[]
    used_copies=set()
    for entry in sorted(targets,key=lambda x:x["wheel_path"]):
        path=entry["wheel_path"]
        cp=[(i,x) for i,x in enumerate(copies) if x.get("repair_pass")=="first" and x.get("dst")==path]
        pt=[(i,x) for i,x in enumerate(patches) if x.get("target","").endswith("/"+path)]
        issues=[]
        if path.startswith("rasterio.libs/"):
            if len(cp)!=1:issues.append("missing_or_ambiguous_real_copy")
            if len(pt)!=1:issues.append("missing_or_ambiguous_real_patchelf")
        else:
            if entry.get("raw_member_path")!=path:issues.append("raw_extension_source_unbound")
            if len(pt)==0:issues.append("missing_extension_patchelf")
        if cp:
            i,x=cp[0];used_copies.add(i)
            if x.get("source_sha256_before")!=x.get("destination_sha256_after"):
                issues.append("copy_hash_mismatch")
            if pt and x.get("destination_sha256_after")!=pt[0][1].get("sha256_before"):
                issues.append("copy_to_patch_hash_break")
        if pt:
            for j,((_,prev),(_,nxt)) in enumerate(zip(pt,pt[1:])):
                if prev.get("sha256_after")!=nxt.get("sha256_before"):
                    issues.append("patchelf_chain_break_"+str(j))
            if pt[-1][1].get("sha256_after")!=entry["repair_1_sha256"]:
                issues.append("last_patch_to_wheel_hash_break")
        issues.extend(["wheel_zip_extraction_not_observed","wheel_zip_insertion_not_observed"])
        result.append({"wheel_path":path,"raw_extension_sha256":entry.get("origin_raw_extension_sha256"),
           "copy_events":[{"sequence":i+1,"src":x["src"],"dst":x["dst"],
             "source_sha256":x.get("source_sha256_before"),"copied_sha256":x.get("destination_sha256_after")} for i,x in cp],
           "patchelf_events":[{"sequence":i+1,"argv":x.get("argv"),"sha256_before":x.get("sha256_before"),
             "sha256_after":x.get("sha256_after")} for i,x in pt],
           "final_sha256":entry["repair_1_sha256"],"issues":sorted(set(issues)),
           "complete":False})
    first=[x for x in copies if x.get("repair_pass")=="first"]
    second=[x for x in copies if x.get("repair_pass")=="second"]
    return {"schema":"weather_router.f7.l12.elf_observed_links.v1",
        "elf_count":len(result),"bundled_elf_count":sum(x["wheel_path"].startswith("rasterio.libs/") for x in result),
        "observed_copy_events_first":len(first),"observed_copy_events_second":len(second),
        "linked_real_first_copy_events":len(used_copies),"observed_patchelf_events":len(patches),
        "unlinked_first_copy_events":len(first)-len(used_copies),
        "fully_proven_elf_count":0,"complete_trace":False,
        "distribution":"BLOCKED","ha_installation":"BLOCKED","entries":result}

def main(argv):
    if len(argv)!=5:raise SystemExit(2)
    r=correlate(read_jsonl(argv[1],10000),read_jsonl(argv[2],10000),json.loads(Path(argv[3]).read_text()))
    Path(argv[4]).write_text(json.dumps(r,sort_keys=True,indent=2)+"\n")
    print("F7-L12 OBSERVED ELF LINKS",r["elf_count"],r["linked_real_first_copy_events"],r["observed_patchelf_events"],"APPROVAL BLOCKED")
if __name__=="__main__":main(sys.argv)
