"""F7 isolated CI-only patchelf subprocess trace; no installation or approvals.

Wrapper invoked by auditwheel through PATH; records exact mutating subprocess
arguments and bounded before/after ELF file hashes. NOT a proof of library copies
performed by Python itself, and not an independent provenance attestation.
"""
from __future__ import annotations
import hashlib, json, os, pathlib, subprocess, sys
REAL="/usr/bin/patchelf"
LOG="/wheelhouse/f7-patchelf-operations-unapproved.jsonl"
def digest(p):
    try:
        p=pathlib.Path(p)
        if not p.is_file() or p.is_symlink() or p.stat().st_size > 100*1024*1024:return None
        h=hashlib.sha256()
        with p.open("rb") as f:
            for b in iter(lambda:f.read(1048576),b""):h.update(b)
        return h.hexdigest()
    except OSError:return None
def main(args):
    if os.getenv("GITHUB_ACTIONS")!="true" or os.getenv("WR_OPERA_ISOLATED_CI")!="1":
        return 97
    # patchelf version and nonmutating reads are forwarded unmodified.
    if not args or args[0] in ("--version","--help"):
        return subprocess.run([REAL,*args],check=False).returncode
    # Patchelf's documented positional filename is the final operand.
    target=args[-1]
    before=digest(target)
    rc=subprocess.run([REAL,*args],check=False).returncode
    after=digest(target)
    row={"schema":"weather_router.f7.actual_patchelf_command.v1",
         "argv":["patchelf",*args],"target":target,
         "sha256_before":before,"sha256_after":after,
         "exit_code":rc,"hashes_are_observations_not_signature":True}
    with open(LOG,"a",encoding="utf-8") as f:
        f.write(json.dumps(row,sort_keys=True)+"\n")
    return rc
if __name__=="__main__":raise SystemExit(main(sys.argv[1:]))
