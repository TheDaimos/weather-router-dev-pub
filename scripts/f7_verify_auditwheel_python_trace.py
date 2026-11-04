"""F7-L09 validate genuine Python auditwheel file operations; fail closed."""
import json
from pathlib import Path
import sys

SCHEMA="weather_router.f7.actual_python_file_operation.v1"
ALLOWED={"shutil.copyfile","shutil.copy2","shutil.move","posix.rename","posix.replace","os.rename","os.replace"}
def verify(path):
    rows=[]
    for i,line in enumerate(Path(path).read_text().splitlines()):
        if i>=10000 or len(line)>30000:raise ValueError("trace_bounds")
        r=json.loads(line)
        if r.get("schema")!=SCHEMA or r.get("repair_pass") not in {"first","second"}:
            raise ValueError("trace_schema")
        if r.get("operation") not in ALLOWED or not r.get("no_approval"):
            raise ValueError("trace_op")
        for key in ("source_sha256_before","source_sha256_after","destination_sha256_before","destination_sha256_after"):
            h=r.get(key)
            if h is not None and (not isinstance(h,str) or len(h)!=64 or set(h)-set("0123456789abcdef")):
                raise ValueError("invalid_hash")
        rows.append(r)
    counts={p:sum(x["repair_pass"]==p for x in rows) for p in ("first","second")}
    # Depending on auditwheel's Python implementation, direct open/writes might
    # bypass the wrapped helpers. Never claim completeness from empty results.
    return {"schema":"weather_router.f7.python_copy_rename_observations.v1",
            "events":len(rows),"counts_by_repair":counts,
            "events_have_no_synthetic_reconstruction":True,
            "zipfile_and_raw_open_operations_fully_captured":False,
            "full_101_elf_transformations_proven":False,
            "distribution":"BLOCKED","ha_installation":"BLOCKED"}
if __name__=="__main__":
    if len(sys.argv)!=3:raise SystemExit(2)
    try:
        obj=verify(sys.argv[1])
        Path(sys.argv[2]).write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n")
        print("F7 ACTUAL PYTHON COPY/RENAME TRACE:",obj["counts_by_repair"],
              "not a complete wheel file-operation transcript")
    except (OSError,ValueError,KeyError,json.JSONDecodeError):
        raise SystemExit(1)
