"""F7 CI-only read-only comparison of two independently auditwheel-repaired wheels.

Produces diagnostic JSON without granting distribution, installation or runtime use.
"""
from __future__ import annotations

import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path

MAX_WHEEL = 250 * 1024 * 1024
MAX_FILES = 10000

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def inventory(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or not (0 < path.stat().st_size <= MAX_WHEEL):
        raise ValueError("wheel path/size rejected")
    files = {}
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        if len(entries) > MAX_FILES:
            raise ValueError("too many members")
        for item in entries:
            name = item.filename
            parts = name.rstrip("/").split("/")
            if (name.startswith("/") or "\\" in name or
                any(p in ("", ".", "..") for p in parts) or name in files):
                raise ValueError("unsafe or duplicate ZIP member")
            kind = (item.external_attr >> 16) & 0o170000
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError("unsafe ZIP member type")
            # Stream each file; no extraction and no unbounded decompression.
            h = hashlib.sha256()
            length = 0
            if not item.is_dir():
                with z.open(item) as src:
                    for block in iter(lambda: src.read(1024 * 1024), b""):
                        length += len(block)
                        if length > 700 * 1024 * 1024:
                            raise ValueError("oversized uncompressed member")
                        h.update(block)
                if length != item.file_size:
                    raise ValueError("ZIP size mismatch")
            files[name] = {
                "sha256": h.hexdigest() if not item.is_dir() else None,
                "size": item.file_size,
                "compressed": item.compress_size,
                "date_time": list(item.date_time),
                "compress_type": item.compress_type,
                "external_attr": item.external_attr,
                "flag_bits": item.flag_bits,
                "create_system": item.create_system,
                "extra_sha256": hashlib.sha256(item.extra).hexdigest(),
                "comment_sha256": hashlib.sha256(item.comment).hexdigest(),
            }
    return {"sha256": digest(path), "wheel_bytes": path.stat().st_size, "members": files}

def compare(left: Path, right: Path) -> dict:
    if left.resolve() == right.resolve():
        raise ValueError("independent repair outputs required")
    if left.name != right.name or not left.name.endswith(".whl"):
        raise ValueError("different wheel product names")
    a, b = inventory(left), inventory(right)
    names = sorted(set(a["members"]) | set(b["members"]))
    changed = [n for n in names if a["members"].get(n) != b["members"].get(n)]
    return {
        "schema": "weather_router.f7.repaired_double_comparison.v1",
        "status": "BIT_IDENTICAL_UNAPPROVED" if a["sha256"] == b["sha256"] else "DIFFERENT_UNAPPROVED",
        "wheel_name": left.name,
        "first_sha256": a["sha256"], "second_sha256": b["sha256"],
        "first_bytes": a["wheel_bytes"], "second_bytes": b["wheel_bytes"],
        "first_member_count": len(a["members"]), "second_member_count": len(b["members"]),
        "different_member_count": len(changed),
        "different_member_names": changed,
        "difference_details": {
            n: {"first": a["members"].get(n), "second": b["members"].get(n)}
            for n in changed
        },
        "independent_build_environment_proven": False,
        "source_provenance_verified": False,
        "licenses_cleared": False,
        "distribution": "BLOCKED",
        "ha_installation": "BLOCKED",
        "opera_activation": "BLOCKED",
    }

def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: probe_f7_repaired_double.py first.whl second.whl", file=sys.stderr)
        return 2
    try:
        result = compare(Path(argv[1]), Path(argv[2]))
    except (ValueError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
        print(f"F7 REPAIRED DOUBLE REJECTED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
