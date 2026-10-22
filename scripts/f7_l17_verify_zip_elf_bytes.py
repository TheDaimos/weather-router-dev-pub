"""F7-L17: correlate actual ZIP payload observations to two finished wheels.

Archive reads are independent AFTER repair; never promote hash equality into an
unobserved copy/patch/compile operation. Fail closed for missing ZIP ELF writes.
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

def sha_bytes(b): return hashlib.sha256(b).hexdigest()

def main(args):
    if len(args)!=6: raise SystemExit(2)
    events=[json.loads(x) for x in Path(args[0]).read_text().splitlines()]
    replay=json.loads(Path(args[1]).read_text())
    chains=json.loads(Path(args[2]).read_text())
    paths={"first":Path(args[3]),"second":Path(args[4])}
    if len(replay["elf_components"])!=101 or len(chains["entries"])!=101:
        raise ValueError("invalid_101_elf_inventory")
    byname={r["wheel_path"]:r for r in replay["elf_components"]}
    if len(byname)!=101: raise ValueError("duplicate_elf")
    result=[]
    for name,wheel in paths.items():
        if not wheel.is_file() or wheel.is_symlink(): raise ValueError("missing_wheel")
        whash=hashlib.file_digest(wheel.open("rb"),"sha256").hexdigest()
        expected=replay[("first" if name=="first" else "second")+"_repaired_wheel_sha256"]
        if whash!=expected: raise ValueError("wheel_hash_drift")
        writes=[e for e in events if e.get("repair_pass")==name and e.get("operation")=="ZipFile.writestr"]
        extracted=[e for e in events if e.get("repair_pass")==name and e.get("operation")=="ZipFile.extract"]
        with zipfile.ZipFile(wheel) as z:
            if len(z.namelist())!=len(set(z.namelist())): raise ValueError("duplicate_zip_member")
            actual={i.filename:i for i in z.infolist()}
            for member,record in byname.items():
                if member not in actual:raise ValueError("missing_final_elf")
                info=actual[member]
                if info.file_size>100*1024*1024:raise ValueError("oversized_elf")
                data=z.read(member)
                finalhash=sha_bytes(data)
                expectedhash=record["repair_1_sha256" if name=="first" else "repair_2_sha256"]
                matches=[x for x in writes if x.get("member_name")==member]
                observed=len(matches)==1 and matches[0].get("supplied_sha256")==finalhash and matches[0].get("supplied_bytes")==len(data)
                if finalhash!=expectedhash:raise ValueError("replay_final_hash_drift")
                result.append({"repair_pass":name,"wheel_member":member,"completed_zip_sha256":finalhash,
                    "completed_uncompressed_bytes":len(data),"observed_unique_writestr_sha_match":observed,
                    "actual_writestr_count":len(matches),"missing_history":
                    ["compiler_and_linker_origin" if not member.startswith("rasterio.libs/") else "original_apk_signature",
                     "all_intermediate_direct_file_operations"],
                    "complete_provenance":False})
    observed=sum(x["observed_unique_writestr_sha_match"] for x in result)
    out={"schema":"weather_router.f7.l17.actual_zip_elf_bytes.v1",
         "elf_members_per_pass":101,"observed_writestr_elf_members":observed,
         "total_elf_pass_entries":len(result),
         "zip_events_total":len(events),
         "actual_extract_events":sum(e.get("operation")=="ZipFile.extract" for e in events),
         "all_101_elf_operations_proven":False,"distribution":"BLOCKED",
         "ha_installation":"BLOCKED","entries":result}
    Path(args[5]).write_text(json.dumps(out,sort_keys=True,indent=2)+"\n")
    if observed!=202: raise ValueError("missing_or_mismatched_actual_zip_byte_events")
    print("F7-L17 ZIP ELF BYTE EDGES",observed,"/202; FULL PROVENANCE BLOCKED")

if __name__=="__main__":main(sys.argv[1:])
