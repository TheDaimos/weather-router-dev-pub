"""F7-L14: observe ACTUAL zipfile write/extract API calls in isolated auditwheel.
Events alone DO NOT prove all ZIP member transitions, raw open operations,
archive finalization or identity of all 101 ELF. No native approvals.
"""
import hashlib
import json
import os
from pathlib import Path
import zipfile

LOG="/wheelhouse/f7-wheel-zip-operations-unapproved.jsonl"
PASS=os.environ.get("F7_TRACE_PASS","unknown")
_BUSY=False

def _sha(path):
    try:
        p=Path(path)
        if not p.is_file() or p.is_symlink() or p.stat().st_size>100*1024*1024:return None
        h=hashlib.sha256()
        with p.open("rb") as f:
            for part in iter(lambda:f.read(1024*1024),b""):h.update(part)
        return h.hexdigest()
    except (TypeError,OSError,ValueError):return None

def _trace(name):
    original=getattr(zipfile.ZipFile,name)
    def call(self,*args,**kwargs):
        global _BUSY
        if _BUSY or not args:return original(self,*args,**kwargs)
        _BUSY=True
        try:
            archive=os.fspath(self.filename) if self.filename else None
            item=str(args[0])
            pre=_sha(args[0]) if name=="write" else None
            try:
                result=original(self,*args,**kwargs)
            except BaseException:
                raise
            row={"schema":"weather_router.f7.l14.observed_zip_api.v1",
                 "repair_pass":PASS,"operation":"ZipFile."+name,
                 "archive":archive,"member_argument":item,"file_sha256_before":pre,
                 "archive_sha256_after":None,"member_sha256_after":None,
                 "archive_finalization_observed":False,"distribution":"BLOCKED"}
            with open(LOG,"a",encoding="utf-8") as fd:
                fd.write(json.dumps(row,sort_keys=True)+"\n")
            return result
        finally:_BUSY=False
    setattr(zipfile.ZipFile,name,call)

if os.getenv("GITHUB_ACTIONS")=="true" and os.getenv("WR_OPERA_ISOLATED_CI")=="1" and Path("/wheelhouse").is_dir():
    for method in ("extract","extractall","write","writestr"):
        _trace(method)
