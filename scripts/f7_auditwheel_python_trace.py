"""Read-only, isolated F7 auditwheel Python file-operation observation.

Loaded through a disposable CI-only sitecustomize shim before genuine auditwheel.
Records calls to shutil.copyfile, shutil.copy2, shutil.move, os.rename and
os.replace, with file hashes before/after each call. This is not a complete
trace of wheeltools archive rewriting, hardlinks or all native operations.
"""
import hashlib
import json
import os
import pathlib
import shutil

LOG = "/wheelhouse/f7-auditwheel-python-operations-unapproved.jsonl"
PASS = os.environ.get("F7_TRACE_PASS", "unknown")
MAX = 100 * 1024 * 1024
_active = False

def _hash(path):
    try:
        p = pathlib.Path(path)
        if not p.is_file() or p.is_symlink() or not 0 < p.stat().st_size <= MAX:
            return None
        h = hashlib.sha256()
        with p.open("rb") as fd:
            for chunk in iter(lambda: fd.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, TypeError, ValueError):
        return None

def _wrap(module, name):
    old = getattr(module, name)
    def traced(*args, **kwargs):
        global _active
        if _active or len(args) < 2:
            return old(*args, **kwargs)
        src, dst = args[:2]
        _active = True
        try:
            before_src, before_dst = _hash(src), _hash(dst)
        finally:
            _active = False
        _active = True
        try:
            result = old(*args, **kwargs)
        except BaseException:
            _active = False
            raise
        try:
            after_src, after_dst = _hash(src), _hash(dst)
            entry = {
                "schema": "weather_router.f7.actual_python_file_operation.v1",
                "repair_pass": PASS, "operation": module.__name__ + "." + name,
                "src": os.fspath(src), "dst": os.fspath(dst),
                "source_sha256_before": before_src, "source_sha256_after": after_src,
                "destination_sha256_before": before_dst,
                "destination_sha256_after": after_dst,
                "no_approval": True,
            }
            with open(LOG, "a", encoding="utf-8") as fd:
                fd.write(json.dumps(entry, sort_keys=True) + "\n")
        finally:
            _active = False
        return result
    setattr(module, name, traced)

if os.getenv("GITHUB_ACTIONS") == "true" and os.getenv("WR_OPERA_ISOLATED_CI") == "1" and pathlib.Path("/wheelhouse").is_dir():
    for module, methods in [(shutil, ("copyfile", "copy2", "move")), (os, ("rename", "replace"))]:
        for method in methods:
            _wrap(module, method)
