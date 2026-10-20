"""Offline F7 build-input snapshot: evidence only, never an attestation.

Uses a same-container APK installed database plus declared digests and tool
versions. Never invokes network, installs packages, imports native libraries,
or marks a build reproducible or distributable.
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path

MAX_DB = 8 * 1024 * 1024
HEX = re.compile(r"[a-f0-9]{64}\Z")

def snapshot(apk_db: str, *, wheel_sha256: str, image_digest: str | None = None):
    p = Path(apk_db)
    if not p.is_file() or p.is_symlink() or not 0 < p.stat().st_size <= MAX_DB:
        raise ValueError("invalid_apk_db")
    if not HEX.fullmatch(wheel_sha256):
        raise ValueError("invalid_wheel_sha")
    raw = p.read_bytes()
    packages = []
    for block in raw.decode("utf-8").split("\n\n"):
        fields = {}
        for line in block.splitlines():
            if len(line) >= 3 and line[1] == ":" and line[0] in ("P", "V", "o", "L"):
                fields.setdefault(line[0], line[2:])
        if "P" in fields and "V" in fields:
            packages.append({"name":fields["P"], "version":fields["V"],
                             "origin":fields.get("o"), "declared_license":fields.get("L")})
    if not packages:
        raise ValueError("empty_apk_package_set")
    packages.sort(key=lambda x:(x["name"],x["version"]))
    if image_digest is not None and not re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest):
        raise ValueError("invalid_image_digest")
    return {"schema":"weather_router.f7.build_input_snapshot.v1",
            "status":"EVIDENCE_ONLY_NOT_REPRODUCIBLE",
            "wheel_sha256":wheel_sha256,
            "apk_db_sha256":hashlib.sha256(raw).hexdigest(),
            "apk_packages":packages, "apk_package_count":len(packages),
            "container_image_digest":image_digest,
            "base_image_immutable":image_digest is not None,
            "source_tarball_sha256_verified":False,
            "build_paths_normalized":False,
            "timestamps_normalized":False,
            "second_build_binary_identical":False,
            "signed_provenance":False,
            "binary_distribution":"BLOCKED",
            "ha_installation":"BLOCKED",
            "opera_activation":"BLOCKED"}

def main(argv):
    if len(argv) not in (3,4):
        print("usage: script.py APK_DB WHEEL_SHA256 [sha256:IMAGE_DIGEST]",file=sys.stderr)
        return 2
    try:
        report=snapshot(argv[1],wheel_sha256=argv[2],
                        image_digest=argv[3] if len(argv)==4 else None)
    except (ValueError,OSError,UnicodeError):
        return 1
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
