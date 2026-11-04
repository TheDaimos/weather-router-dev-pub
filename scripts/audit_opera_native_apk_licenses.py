"""F7 source-license candidate mapping from the *actual isolated Alpine build*.

Inputs: inventory JSON from real audited wheel plus Alpine /lib/apk/db/installed
from the SAME disposable CI container. No shell, no network, no package install,
no extraction of Wheel binaries; name-only matches do NOT prove binary origin.
This is NOT license clearance, a signed SBOM, or permission to distribute.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

MAX_DB = 8 * 1024 * 1024
MAX_INVENTORY = 2 * 1024 * 1024
# auditwheel inserts the 8-hex digest BEFORE the dotted SONAME suffix:
# libxerces-c-3-5caca54e.2.so -> libxerces-c-3.2.so,
# libopenblasp-r0-35434127.3.30.so -> libopenblasp-r0.3.30.so.
# Mapping is still filename-only until binary/APK hash provenance is proved.
MANGLED = re.compile(r"-(?:[0-9a-f]{8})(?=\.)")
SCHEMA = "weather_router.f7.native_apk_license_candidates.v1"


def _read_limited(path, max_bytes):
    p = Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size > max_bytes:
        raise ValueError("invalid_input")
    with p.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("input_too_large")
    return raw.decode("utf-8", errors="strict")


def _installed_records(raw):
    """Alpine installed-db F:/R: pairs and P:/V:/L:/o: package headers."""
    for block in raw.split("\n\n"):
        meta, paths, prefix = {}, [], ""
        for line in block.splitlines():
            if len(line) < 2 or line[1] != ":":
                continue
            key, val = line[0], line[2:]
            if key in ("P", "V", "L", "o") and key not in meta:
                meta[key] = val
            elif key == "F":
                prefix = val.strip("/")
            elif key == "R":
                paths.append(prefix + "/" + val if prefix else val)
        if meta.get("P") and meta.get("V"):
            yield {"package": meta["P"], "version": meta["V"],
                   "declared_license": meta.get("L"),
                   "origin": meta.get("o"), "paths": paths}


def audit(inventory_json, apk_db):
    inventory = json.loads(_read_limited(inventory_json, MAX_INVENTORY))
    if (not isinstance(inventory, dict)
            or inventory.get("schema") != "weather_router.f7.native_candidate_inventory.v2"
            or inventory.get("status") != "UNAPPROVED_NOT_DISTRIBUTABLE"
            or inventory.get("target_abi") != "cp314-cp314-musllinux_1_2_x86_64"):
        raise ValueError("unsupported_inventory")
    entries = inventory.get("files")
    if not isinstance(entries, list) or len(entries) != inventory.get("files_count"):
        raise ValueError("incomplete_inventory")
    owners = {}
    packages = {}
    for record in _installed_records(_read_limited(apk_db, MAX_DB)):
        detail = {k: record[k] for k in ("package", "version",
                                        "declared_license", "origin")}
        packages[(detail["package"], detail["version"])] = detail
        for name in record["paths"]:
            owners.setdefault(name, []).append(detail)
    rows = []
    name_only = 0
    unresolved = 0
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("elf_magic"):
            continue
        name = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(name, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid_elf_record")
        original_name = MANGLED.sub("", Path(name).name)
        possible = []
        for location in ("usr/lib", "lib", "usr/local/lib"):
            possible.extend(owners.get(location + "/" + original_name, []))
        unique = {r["package"] + "@" + r["version"]: r for r in possible}
        matches = sorted(unique.values(), key=lambda v: (v["package"], v["version"]))
        if matches:
            name_only += 1
            confidence = "filename_only_not_binary_proof"
        elif name.startswith("rasterio/"):
            matches = [{"package": "rasterio", "version": "1.5.2",
                        "declared_license": inventory["python_distribution_metadata"].get("license_expression"),
                        "origin": "wheel_python_metadata_not_apk"}]
            confidence = "wheel_metadata_not_transitive_binary_license"
        else:
            confidence = "unresolved"
            unresolved += 1
        rows.append({"wheel_path": name, "wheel_sha256": digest,
                     "apk_source_candidates": matches,
                     "attribution_confidence": confidence,
                     "license_review": "REQUIRED"})
    if len(rows) != inventory.get("native_elf_count"):
        raise ValueError("elf_count_mismatch")
    return {
        "schema": SCHEMA,
        "status": "UNAPPROVED_NOT_DISTRIBUTABLE",
        "wheel_sha256": inventory["candidate"]["sha256"],
        "native_elf_count": len(rows),
        "apk_filename_candidate_count": name_only,
        "unresolved_component_count": unresolved,
        "apk_installed_package_count": len(packages),
        "mapping_is_binary_hash_verified": False,
        "declared_apk_licenses_individually_verified": False,
        "license_texts_and_obligations_review": "REQUIRED",
        "cve_scan": "REQUIRED",
        "build_source_provenance_attested": False,
        "full_sbom_approved": False,
        "ha_installation": "BLOCKED",
        "provider_activation": "BLOCKED",
        "elf_candidates": rows,
    }


def main(argv):
    if len(argv) != 3:
        print("usage: audit_opera_native_apk_licenses.py INVENTORY_JSON ALPINE_APK_DB", file=sys.stderr)
        return 2
    try:
        report = audit(argv[1], argv[2])
    except (ValueError, OSError, UnicodeError, KeyError, TypeError):
        print("F7 license candidate inventory rejected", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
