"""Offline F7 native wheel bill-of-materials inventory; no install or publish.

Usage: python scripts/inventory_opera_native_wheel.py <wheel-path> <trusted-sha256>
Output JSON to stdout; do not treat this as a license clearance or a signed SBOM.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from zipfile import ZipFile


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: inventory_opera_native_wheel.py WHEEL TRUSTED_SHA256", file=sys.stderr)
        return 2
    path = Path(argv[1])
    source = Path(__file__).resolve().parents[1] / "custom_components/weather_router/opera_native_package.py"
    spec = importlib.util.spec_from_file_location("f7_native_admission", source)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    # Do not inspect archive content before SHA and size/ZIP admission.
    admission = gate.inspect_candidate(path, argv[2])
    entries = []
    with ZipFile(path) as archive:
        for member in sorted(archive.infolist(), key=lambda e: e.filename):
            if member.is_dir():
                continue
            digest = hashlib.sha256()
            with archive.open(member) as data:
                for part in iter(lambda: data.read(65536), b""):
                    digest.update(part)
            name = member.filename
            native = name.lower().endswith((".so", ".dll", ".dylib")) or ".so." in name.lower()
            legal = any(word in Path(name).name.lower()
                        for word in ("license", "licence", "copyright", "notice", "copying"))
            entries.append({"path": name, "size_bytes": member.file_size,
                            "sha256": digest.hexdigest(), "native": native,
                            "possible_legal_notice": legal})
    report = {
        "schema": "weather_router.f7.native_candidate_inventory.v1",
        "status": "UNAPPROVED_NOT_DISTRIBUTABLE",
        "candidate": admission,
        "components_license_review": "REQUIRED",
        "source_provenance_verified": False,
        "elf_dependency_closure_verified": False,
        "files": entries,
    }
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
