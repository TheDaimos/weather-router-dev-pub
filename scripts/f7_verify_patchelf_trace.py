"""F7 isolated CI fail-closed verification of observed real patchelf invocations.

No claim to cover copies/renames done in auditwheel Python (not intercepted).
"""
import json, pathlib, sys

SCHEMA="weather_router.f7.actual_patchelf_command.v1"
HEX=set("0123456789abcdef")

def inspect(path):
    lines=pathlib.Path(path).read_text().splitlines()
    if len(lines)>10000:raise ValueError("too_many_operations")
    records=[]
    for ix,line in enumerate(lines):
        if len(line)>30000:raise ValueError("oversize")
        x=json.loads(line)
        if x.get("schema")!=SCHEMA or not isinstance(x.get("argv"),list) or x["argv"][0]!="patchelf":
            raise ValueError("unknown_operation")
        for key in ("sha256_before","sha256_after"):
            v=x.get(key)
            if v is not None and (not isinstance(v,str) or len(v)!=64 or any(c not in HEX for c in v)):
                raise ValueError("invalid_digest")
        if x.get("exit_code")!=0:raise ValueError("patchelf_failed")
        records.append({"sequence":ix+1,"argv":x["argv"],"target":x.get("target"),
                        "sha256_before":x.get("sha256_before"),"sha256_after":x.get("sha256_after"),
                        "changed":x.get("sha256_before")!=x.get("sha256_after")})
    return {"schema":"weather_router.f7.patchelf_observed_sequence.v1",
            "observed_commands":len(records),"records":records,
            "python_copy_and_rename_trace_complete":False,
            "all_101_elf_transformations_proven":False,
            "distribution":"BLOCKED","ha_installation":"BLOCKED"}
if __name__=="__main__":
    if len(sys.argv)!=3:raise SystemExit(2)
    try:
        report=inspect(sys.argv[1])
        pathlib.Path(sys.argv[2]).write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
        print("F7 REAL PATCHELF TRACE:",report["observed_commands"],"operations; Python copies NOT traced")
    except (ValueError,KeyError,OSError,json.JSONDecodeError) as exc:
        print("F7 patchelf trace error",exc,file=sys.stderr)
        raise SystemExit(1)
