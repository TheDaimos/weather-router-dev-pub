"""F7: deterministic read-only-verified Rasterio source extraction for isolated CI.

Exactly one official-version sdist is unpacked at a fixed path and freshly
re-extracted before each build. No install, native import, source patching or
binary distribution. Sdist digest is observed, NOT independently attested.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

EXPECTED_NAME = "rasterio-1.5.2.tar.gz"
FIXED_ROOT = Path("/tmp/f7-opera-repro-source")
SOURCE_ROOT = FIXED_ROOT / "rasterio-1.5.2"
MAX_TARBALL = 25 * 1024 * 1024
MAX_EXPANDED = 150 * 1024 * 1024
MAX_ENTRIES = 3000

def prepare(archive_path, *, target=SOURCE_ROOT):
    src = Path(archive_path)
    dest = Path(target)
    if (src.name != EXPECTED_NAME or not src.is_file() or src.is_symlink()
            or not 0 < src.stat().st_size <= MAX_TARBALL):
        raise ValueError("invalid_rasterio_sdist")
    # Only fixed, explicitly bounded CI scratch tree; never touch an arbitrary path.
    if dest != SOURCE_ROOT or dest.parent != FIXED_ROOT or dest.is_symlink():
        raise ValueError("nonfixed_source_path")
    FIXED_ROOT.mkdir(parents=True, exist_ok=True)
    if FIXED_ROOT.is_symlink():
        raise ValueError("symlink_source_root")
    raw_hash = hashlib.sha256()
    with src.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            raw_hash.update(chunk)
    with tarfile.open(src, mode="r:gz") as archive:
        members = archive.getmembers()
        if not 0 < len(members) <= MAX_ENTRIES:
            raise ValueError("invalid_member_count")
        total = 0
        for member in members:
            path = PurePosixPath(member.name)
            parts = path.parts
            if (path.is_absolute() or not parts or parts[0] != "rasterio-1.5.2"
                    or any(p in (".", "..") for p in parts)
                    or not (member.isfile() or member.isdir())
                    or member.size < 0 or member.size > MAX_EXPANDED):
                raise ValueError("unsafe_sdist_member")
            total += member.size
            if total > MAX_EXPANDED:
                raise ValueError("expanded_sdist_too_large")
        # Clean the same fixed scratch directory for the second independent build.
        if dest.exists():
            if not dest.is_dir() or dest.is_symlink():
                raise ValueError("non_directory_source_target")
            shutil.rmtree(dest)
        # Python 3.14 data filter defends ownership, links and special metadata.
        archive.extractall(FIXED_ROOT, filter="data")
    if not (dest / "pyproject.toml").is_file():
        raise ValueError("no_project_metadata")
    return {"schema": "weather_router.f7.fixed_sdist_source.v1",
            "status": "CI_ONLY_NOT_DISTRIBUTABLE",
            "sdist_name": EXPECTED_NAME,
            "sdist_sha256": raw_hash.hexdigest(),
            "archive_entries": len(members),
            "unpacked_declared_bytes": total,
            "fixed_source_path": str(dest),
            "source_sha_independently_attested": False,
            "binary_distribution": "BLOCKED",
            "ha_installation": "BLOCKED",
            "opera_activation": "BLOCKED"}

def main(argv):
    if len(argv) != 2:
        print("usage: f7_prepare_fixed_source.py /wheelhouse/source/rasterio-1.5.2.tar.gz", file=sys.stderr)
        return 2
    try:
        result = prepare(argv[1])
    except (ValueError, OSError, tarfile.TarError):
        print("F7 fixed-source preparation rejected", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
