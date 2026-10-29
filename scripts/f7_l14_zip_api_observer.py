"""F7-L17: observe original ZIP call byte flow in disposable auditwheel CI only.

Do not alter the original method arguments, ordering, compression or returns.
No operation is logged as successful when the original method fails.
"""
import hashlib
import json
import os
from pathlib import Path
import zipfile

LOG = "/wheelhouse/f7-wheel-zip-operations-unapproved.jsonl"
PASS = os.environ.get("F7_TRACE_PASS", "unknown")
_BUSY = False
MAX_HASH_BYTES = 100 * 1024 * 1024

def _file_info(path):
    try:
        p = Path(path)
        if not p.is_file() or p.is_symlink():
            return None, None
        size = p.stat().st_size
        if size > MAX_HASH_BYTES:
            return None, size
        h = hashlib.sha256()
        with p.open("rb") as fd:
            for chunk in iter(lambda: fd.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest(), size
    except (OSError, TypeError, ValueError):
        return None, None

def _content_info(payload):
    if isinstance(payload, (bytes, bytearray)):
        return hashlib.sha256(payload).hexdigest(), len(payload)
    if isinstance(payload, memoryview):
        return hashlib.sha256(payload).hexdigest(), payload.nbytes
    return None, None

def _member_name(member):
    if isinstance(member, zipfile.ZipInfo):
        return member.filename
    if isinstance(member, str):
        return member
    return None

def _trace(name):
    original = getattr(zipfile.ZipFile, name)
    def call(self, *args, **kwargs):
        global _BUSY
        if _BUSY or not args:
            return original(self, *args, **kwargs)
        _BUSY = True
        try:
            archive = os.fspath(self.filename) if self.filename else None
            member = _member_name(args[0])
            supplied_hash = supplied_size = None
            if name == "writestr":
                data = args[1] if len(args) >= 2 else kwargs.get("data")
                supplied_hash, supplied_size = _content_info(data)
            elif name == "write":
                supplied_hash, supplied_size = _file_info(args[0])
            # Invoke the original exactly once, with the original arguments.
            result = original(self, *args, **kwargs)
            extracted = None
            extracted_hash = extracted_size = None
            if name == "extract":
                extracted = os.fspath(result)
                extracted_hash, extracted_size = _file_info(extracted)
            row = {
                "schema": "weather_router.f7.l17.observed_zip_bytes.v1",
                "repair_pass": PASS, "operation": "ZipFile." + name,
                "archive": archive, "member_name": member,
                "supplied_sha256": supplied_hash, "supplied_bytes": supplied_size,
                "file_sha256_before": supplied_hash,
                "extracted_path": extracted, "extracted_sha256": extracted_hash,
                "extracted_bytes": extracted_size,
                "operation_succeeded": True, "archive_finalized": False,
                "distribution": "BLOCKED",
            }
            with open(LOG, "a", encoding="utf-8") as fd:
                fd.write(json.dumps(row, sort_keys=True) + "\n")
            return result
        finally:
            _BUSY = False
    setattr(zipfile.ZipFile, name, call)

if os.getenv("GITHUB_ACTIONS") == "true" and os.getenv("WR_OPERA_ISOLATED_CI") == "1" and Path("/wheelhouse").is_dir():
    for method in ("extract", "extractall", "write", "writestr"):
        _trace(method)
