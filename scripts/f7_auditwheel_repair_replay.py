"""F7-L04: bound, read-only, per-member evidence for two REAL auditwheel repairs.

The CI has already run auditwheel twice on the same raw wheel. This probe binds
input hash, both output hashes and EACH ELF output to the identical replay.
A matching hash proves reproducibility of the whole transformation result,
NOT proof of every individual patchelf command or a license approval.
"""
from __future__ import annotations
import hashlib
import json
import pathlib
import re
import sys
import zipfile
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX = 250*1024*1024

def hash_file(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()

def elf_members(path):
    if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=MAX:
        raise ValueError("invalid_wheel")
    out={}
    with zipfile.ZipFile(path) as z:
        if len(z.namelist())!=len(set(z.namelist())):raise ValueError("duplicate_members")
        for entry in z.infolist():
            if entry.is_dir() or entry.file_size<4:continue
            if entry.file_size>MAX:raise ValueError("oversized_member")
            with z.open(entry) as f:
                data=f.read(4)
                if data!=b"\x7fELF":continue
                h=hashlib.sha256(data)
                n=4
                for block in iter(lambda:f.read(1024*1024),b""):
                    n+=len(block)
                    if n>70*1024*1024:raise ValueError("oversized_elf")
                    h.update(block)
            if entry.filename.startswith("/") or ".." in pathlib.PurePosixPath(entry.filename).parts:
                raise ValueError("unsafe_path")
            out[entry.filename]={"sha256":h.hexdigest(),"bytes":n}
    return out

def report(raw, first, second, auditwheel_version, patchelf_version):
    raw,first,second=map(pathlib.Path,(raw,first,second))
    if first.resolve()==second.resolve():raise ValueError("must use separate outputs")
    original,one,two=elf_members(raw),elf_members(first),elf_members(second)
    rawhash,sha1,sha2=(hash_file(p) for p in (raw,first,second))
    if not original or len(one)!=101 or len(two)!=101 or set(one)!=set(two):
        raise ValueError("unexpected_native_inventory")
    rows=[]
    for name in sorted(one):
        a,b=one[name],two[name]
        rows.append({"wheel_path":name,"repair_1_sha256":a["sha256"],
                     "repair_2_sha256":b["sha256"],"reproduced_bytes":a==b,
                     "origin_raw_extension_sha256":original.get(name,{}).get("sha256"),
                     "raw_member_path":name if name in original else None,
                     "source_library_transformation_trace_complete":False})
    return {"schema":"weather_router.f7.auditwheel_two_real_repairs.v1",
            "raw_wheel_sha256":rawhash,"first_repaired_wheel_sha256":sha1,
            "second_repaired_wheel_sha256":sha2,
            "auditwheel_version":auditwheel_version,
            "patchelf_version":patchelf_version,
            "raw_elf_count":len(original),"repaired_elf_count":len(rows),
            "identical_repaired_bytes":sha1==sha2,
            "identical_elf_members":sum(x["reproduced_bytes"] for x in rows),
            "all_steps_traced":False,
            "approval":"BLOCKED","ha_installation":"BLOCKED","distribution":"BLOCKED",
            "elf_components":rows}

if __name__=="__main__":
    if len(sys.argv)!=7:raise SystemExit("raw first second auditwheel_version patchelf_version output")
    r=report(*sys.argv[1:6])
    pathlib.Path(sys.argv[6]).write_text(json.dumps(r,sort_keys=True,indent=2)+"\n")
    print("F7 AUDITWHEEL REAL REPAIR REPLAY:",r["identical_repaired_bytes"],
          r["identical_elf_members"],"/101 ELF; full patch trace NOT approved")
