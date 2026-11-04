"""F7-L13: independently classify two REAL auditwheel repair passes.

Read only observed JSONL copies/patchelf subprocesses plus 101 authentic wheel
member hashes. Do not invent ZIP or compiler operations. Never approve native
release, even when measured hash edges are consistent.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys

def _valid_digest(d):
    return isinstance(d,str) and len(d)==64 and all(c in "0123456789abcdef" for c in d)

def read_jsonl(path, limit=10000):
    lines=Path(path).read_text().splitlines()
    if len(lines)>limit: raise ValueError("too_many_events")
    return [json.loads(x) for x in lines]

def correlate(copies, patches, replay):
    entries=replay["elf_components"]
    if len(entries)!=101 or not replay["identical_repaired_bytes"] or replay["identical_elf_members"]!=101:
        raise ValueError("101_elf_reproduction_unverified")
    if len({x["wheel_path"] for x in entries})!=101:
        raise ValueError("duplicate_wheel_member")
    paths=set(x["wheel_path"] for x in entries)
    roots=[]
    classified=[]
    for i,x in enumerate(patches):
        match=[p for p in paths if x.get("target","").endswith("/"+p)]
        if len(match)!=1 or x.get("exit_code")!=0:raise ValueError("unmapped_or_failed_real_patchelf")
        path=match[0]
        root=x["target"][:-(len(path)+1)]
        if root not in roots:roots.append(root)
        if len(roots)>2:raise ValueError("more_than_two_repair_roots")
        classified.append((i,root,path,x))
    if len(roots)!=2 or not all(x.startswith("/tmp/") for x in roots):
        raise ValueError("missing_two_actual_repair_roots")
    # The two actual invocations must occupy non-overlapping blocks in the
    # original append-only process log; otherwise per-pass attribution is unsafe.
    positions=[[i for i,r,_,_ in classified if r==root] for root in roots]
    if positions[0][-1]>=positions[1][0]:raise ValueError("interleaved_unattributable_repairs")
    if set(x.get("repair_pass") for x in copies)!={"first","second"}:
        raise ValueError("missing_copy_pass")
    rows=[]
    used={"first":set(),"second":set()}
    integrity=0
    no_patches=[]
    for record in sorted(entries,key=lambda x:x["wheel_path"]):
        path=record["wheel_path"]
        bundled=path.startswith("rasterio.libs/")
        issues=[]
        per_pass={}
        for name,root,final in (("first",roots[0],record["repair_1_sha256"]),
                                ("second",roots[1],record["repair_2_sha256"])):
            cp=[(i,c) for i,c in enumerate(copies) if c.get("repair_pass")==name and c.get("dst")==path]
            pp=[(i,p) for i,r,t,p in classified if r==root and t==path]
            if bundled and len(cp)!=1:issues.append(name+"_ambiguous_or_missing_copy")
            if not bundled and cp:issues.append(name+"_unexpected_source_copy")
            if bundled and len(pp)!=1:issues.append(name+"_unexpected_patch_count")
            if not bundled and not _valid_digest(record.get("origin_raw_extension_sha256")):
                issues.append(name+"_raw_extension_origin_missing")
            if cp:
                i,c=cp[0];used[name].add(i)
                if c.get("source_sha256_before")!=c.get("destination_sha256_after"):
                    issues.append(name+"_copy_hash_mismatch")
                if pp and c.get("destination_sha256_after")!=pp[0][1].get("sha256_before"):
                    issues.append(name+"_copy_patch_hash_break")
            if not bundled and pp and record["origin_raw_extension_sha256"]!=pp[0][1].get("sha256_before"):
                issues.append(name+"_raw_extension_patch_hash_break")
            for (_,prev),(_,nxt) in zip(pp,pp[1:]):
                if prev.get("sha256_after")!=nxt.get("sha256_before"):
                    issues.append(name+"_within_pass_patch_hash_break")
            if pp and pp[-1][1].get("sha256_after")!=final:
                issues.append(name+"_last_patch_final_hash_break")
            if not pp:
                if record.get("origin_raw_extension_sha256")!=final:
                    issues.append(name+"_no_patch_but_final_changed")
                else:no_patches.append({"pass":name,"wheel_path":path,"verified_unchanged_bytes":True})
            per_pass[name]={"root":root,"copies":[{"index":i+1,"source":c["src"],
                    "source_sha256":c.get("source_sha256_before"),
                    "destination_sha256":c.get("destination_sha256_after")} for i,c in cp],
                "patches":[{"index":i+1,"argv":p["argv"],"sha256_before":p["sha256_before"],
                    "sha256_after":p["sha256_after"]} for i,p in pp],
                "final_sha256":final}
        if not issues:integrity+=1
        rows.append({"wheel_path":path,"origin_raw_extension_sha256":record.get("origin_raw_extension_sha256"),
             "observed_hash_edges_consistent":not issues,"hash_edge_issues":sorted(set(issues)),
             "unobserved_stages":["wheel_zip_extraction","wheel_zip_insertion"]+
                 ([] if bundled else ["C_compilation","C_linking","source_archive_extraction"]),
             "passes":per_pass,"complete_provenance":False})
    leftovers={name:sum(x.get("repair_pass")==name for x in copies)-len(used[name]) for name in used}
    return {"schema":"weather_router.f7.l13.observed_elf_passes.v1","elf_count":101,
        "bundled_count":sum(x["wheel_path"].startswith("rasterio.libs/") for x in rows),
        "source_extensions_count":sum(not x["wheel_path"].startswith("rasterio.libs/") for x in rows),
        "actual_patchelf_roots":roots,"patchelf_calls_per_pass":{name:len(positions[i]) for i,name in enumerate(("first","second"))},
        "copy_calls_per_pass":{name:sum(x.get("repair_pass")==name for x in copies) for name in used},
        "linked_copy_calls_per_pass":{name:len(used[name]) for name in used},
        "unlinked_copy_calls_per_pass":leftovers,
        "hash_edges_consistent_elf_count":integrity,
        "verified_unchanged_extensions":no_patches,
        "fully_proven_elf_count":0,"all_steps_traced":False,
        "distribution":"BLOCKED","ha_installation":"BLOCKED","entries":rows}

def main(argv):
    if len(argv)!=5:raise SystemExit(2)
    data=correlate(read_jsonl(argv[1]),read_jsonl(argv[2]),json.loads(Path(argv[3]).read_text()))
    Path(argv[4]).write_text(json.dumps(data,indent=2,sort_keys=True)+"\n")
    print("F7-L13 OBSERVED REAL PASSES:",data["hash_edges_consistent_elf_count"],
          "/101 measured hash edge sets; ZIP/COMPILER/INSTALL STILL BLOCKED")
if __name__=="__main__":main(sys.argv)
