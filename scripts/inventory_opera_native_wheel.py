"""Read-only F7 native wheel evidence inventory. Never installs, publishes, or loads the wheel.

Usage: python scripts/inventory_opera_native_wheel.py WHEEL TRUSTED_SHA256 [--require-elf]
SHA must be independently authenticated before any install decision. Computing a
hash from the same candidate in CI is *inventory identification*, not provenance.
Output is a candidate SBOM evidence document, NOT an approved SPDX/CycloneDX SBOM.
"""
from __future__ import annotations

from email.parser import Parser
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

MAX_READ_ELF = 120 * 1024 * 1024
SO_PATTERN = re.compile(r"\.so(?:\.|$)", flags=re.I)
NEEDED = re.compile(r"\(NEEDED\).*?\[(.*?)\]")
SONAME = re.compile(r"\(SONAME\).*?\[(.*?)\]")
RPATH = re.compile(r"\((?:RUNPATH|RPATH)\).*?\[(.*?)\]")


def _elf_dependencies(stream, size, *, require_elf=False):
    """Bounded file and readelf subprocess; no archive-supplied executable is run."""
    if size > MAX_READ_ELF:
        if require_elf:
            raise ValueError("oversize_native_object")
        return {"elf_audit": "unverified_too_large", "needed": [], "soname": None, "rpath": []}
    if shutil.which("readelf") is None:
        if require_elf:
            raise ValueError("readelf_missing")
        return {"elf_audit": "not_available", "needed": [], "soname": None, "rpath": []}
    with tempfile.TemporaryDirectory(prefix="wr-f7-elf-") as folder:
        src = Path(folder) / "object.elf"
        with src.open("xb") as dest:
            for block in iter(lambda: stream.read(65536), b""):
                dest.write(block)
        try:
            result = subprocess.run(
                ["readelf", "-d", str(src)], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=6, check=False)
        except (OSError, subprocess.TimeoutExpired):
            if require_elf:
                raise ValueError("readelf_failed") from None
            return {"elf_audit": "failed", "needed": [], "soname": None, "rpath": []}
    if result.returncode:
        if require_elf:
            raise ValueError("invalid_elf_or_readelf_error")
        return {"elf_audit": "failed", "needed": [], "soname": None, "rpath": []}
    decoded = result.stdout[:65536].decode("utf-8", errors="replace")
    return {"elf_audit": "readelf_dynamic_pass",
            "needed": sorted(set(NEEDED.findall(decoded))),
            "soname": next(iter(SONAME.findall(decoded)), None),
            "rpath": sorted(set(RPATH.findall(decoded)))}


def inventory(path, trusted_sha256, *, require_elf=False):
    source = Path(__file__).resolve().parents[1] / (
        "custom_components/weather_router/opera_native_package.py")
    spec = importlib.util.spec_from_file_location("f7_native_admission", source)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    admission = gate.inspect_candidate(path, trusted_sha256)
    entries = []
    native_files = []
    license_files = []
    metadata = {"name": None, "version": None, "license_expression": None,
                "license": None, "license_files": [], "requires_dist": []}
    with ZipFile(path) as archive:
        for member in sorted(archive.infolist(), key=lambda e: e.filename):
            if member.is_dir():
                continue
            digest = hashlib.sha256()
            with archive.open(member) as data:
                prefix = data.read(4)
                digest.update(prefix)
                for part in iter(lambda: data.read(65536), b""):
                    digest.update(part)
            name = member.filename
            native_hint = bool(SO_PATTERN.search(Path(name).name))
            is_elf = prefix == b"\x7fELF"
            legal = any(word in Path(name).name.lower()
                        for word in ("license", "licence", "copyright", "notice", "copying"))
            row = {"path": name, "size_bytes": member.file_size,
                   "sha256": digest.hexdigest(), "native": native_hint or is_elf,
                   "elf_magic": is_elf, "possible_legal_notice": legal}
            if is_elf:
                with archive.open(member) as data:
                    elf = _elf_dependencies(data, member.file_size, require_elf=require_elf)
                row.update(elf)
                native_files.append(name)
            elif native_hint and require_elf:
                raise ValueError("native_object_missing_elf_magic")
            if legal:
                license_files.append(name)
            if name == "rasterio-1.5.2.dist-info/METADATA":
                with archive.open(member) as data:
                    raw = data.read(min(member.file_size, 256 * 1024) + 1)
                    if len(raw) > 256 * 1024:
                        raise ValueError("oversize_package_metadata")
                parsed = Parser().parsestr(raw.decode("utf-8", errors="replace"))
                metadata = {
                    "name": parsed.get("Name"), "version": parsed.get("Version"),
                    "license_expression": parsed.get("License-Expression"),
                    "license": parsed.get("License"),
                    "license_files": parsed.get_all("License-File", []),
                    "requires_dist": parsed.get_all("Requires-Dist", [])}
            entries.append(row)
    internal_names = {Path(n).name for n in native_files}
    # A SONAME is often different from the bundled renamed filename. This
    # classification is a hint; real dependency closure stays UNVERIFIED.
    sonames = {e.get("soname") for e in entries if e.get("soname")}
    bundled = internal_names | sonames
    external = sorted({dep for row in entries for dep in row.get("needed", [])
                       if dep not in bundled})
    report = {
        "schema": "weather_router.f7.native_candidate_inventory.v2",
        "status": "UNAPPROVED_NOT_DISTRIBUTABLE",
        "candidate": admission,
        "target_abi": "cp314-cp314-musllinux_1_2_x86_64",
        "files_count": len(entries),
        "native_elf_count": len(native_files),
        "legal_notice_file_candidates": sorted(license_files),
        "python_distribution_metadata": metadata,
        "elf_external_dependency_names": external,
        "elf_dependency_closure_verified": False,
        "components_license_review": "REQUIRED",
        "vulnerability_review": "REQUIRED",
        "source_provenance_verified": False,
        "sha256_independently_attested": False,
        "spdx_or_cyclonedx_compliant_sbom": False,
        "ha_installation": "BLOCKED",
        "opera_provider_activation": "BLOCKED",
        "files": entries,
    }
    return report


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4) or (len(argv) == 4 and argv[3] != "--require-elf"):
        print("usage: inventory_opera_native_wheel.py WHEEL TRUSTED_SHA256 [--require-elf]",
              file=sys.stderr)
        return 2
    try:
        report = inventory(argv[1], argv[2], require_elf=len(argv) == 4)
    except (ValueError, OSError) as exc:
        # Safe fixed categories. Do not print paths or native exception text.
        print("F7 candidate inventory rejected", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
