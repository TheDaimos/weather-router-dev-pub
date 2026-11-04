"""Compare two independently collected F7 wheel inventory JSONs, offline.

The comparison verifies content *differences*, not the authenticity of the
input reports, signing, or reproducibility of the build process.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}\Z")
SCHEMA = "weather_router.f7.native_inventory_comparison.v1"

def _read(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= MAX_BYTES:
        raise ValueError("invalid_inventory_file")
    with p.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("oversize_inventory")
    value = json.loads(data)
    if (not isinstance(value, dict)
            or value.get("schema") != "weather_router.f7.native_candidate_inventory.v2"
            or value.get("status") != "UNAPPROVED_NOT_DISTRIBUTABLE"
            or value.get("target_abi") != "cp314-cp314-musllinux_1_2_x86_64"
            or not isinstance(value.get("files"), list)
            or len(value["files"]) != value.get("files_count")
            or not isinstance(value.get("candidate"), dict)
            or not isinstance(value["candidate"].get("sha256"), str)
            or not HASH.fullmatch(value["candidate"]["sha256"])):
        raise ValueError("untrusted_inventory_schema")
    by_name = {}
    for item in value["files"]:
        if (not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not item["path"].startswith(("rasterio/", "rasterio.libs/", "rasterio-1.5.2.dist-info/"))
                or item["path"] in by_name
                or not isinstance(item.get("sha256"), str)
                or not HASH.fullmatch(item["sha256"])
                or type(item.get("size_bytes")) is not int
                or item["size_bytes"] < 0
                or type(item.get("elf_magic")) is not bool):
            raise ValueError("untrusted_file_record")
        by_name[item["path"]] = item
    if sum(x["elf_magic"] for x in by_name.values()) != value.get("native_elf_count"):
        raise ValueError("invalid_elf_count")
    return value, by_name

def _kind(name):
    if name.endswith(".dist-info/RECORD"):
        return "wheel_record"
    if name.startswith("rasterio.libs/"):
        return "bundled_native_libraries"
    if name.startswith("rasterio/") and ".so" in name:
        return "rasterio_native_extensions"
    if name.startswith("rasterio/proj_data/") or name.startswith("rasterio/gdal_data/"):
        return "projection_and_gdal_resources"
    return "other_package_files"

def compare(left_path, right_path):
    a, ma = _read(left_path)
    b, mb = _read(right_path)
    removed = sorted(set(ma) - set(mb))
    added = sorted(set(mb) - set(ma))
    changed = []
    for name in sorted(set(ma) & set(mb)):
        old, new = ma[name], mb[name]
        if old["sha256"] != new["sha256"] or old["size_bytes"] != new["size_bytes"]:
            changed.append({"wheel_path": name, "category": _kind(name),
                            "old_sha256": old["sha256"], "new_sha256": new["sha256"],
                            "old_bytes": old["size_bytes"], "new_bytes": new["size_bytes"]})
    native_a = {k:v["sha256"] for k,v in ma.items() if k.startswith("rasterio.libs/")}
    native_b = {k:v["sha256"] for k,v in mb.items() if k.startswith("rasterio.libs/")}
    resources_a = {k:v["sha256"] for k,v in ma.items()
                   if k.startswith(("rasterio/proj_data/", "rasterio/gdal_data/"))}
    resources_b = {k:v["sha256"] for k,v in mb.items()
                   if k.startswith(("rasterio/proj_data/", "rasterio/gdal_data/"))}
    return {
        "schema": SCHEMA,
        "status": "NON_DISTRIBUTABLE_EVIDENCE_ONLY",
        "left_wheel_sha256": a["candidate"]["sha256"],
        "right_wheel_sha256": b["candidate"]["sha256"],
        "wheel_sha256_identical": a["candidate"]["sha256"] == b["candidate"]["sha256"],
        "files_left": len(ma), "files_right": len(mb),
        "elf_left": a["native_elf_count"], "elf_right": b["native_elf_count"],
        "added_files": added, "removed_files": removed,
        "changed_member_count": len(changed), "changed_members": changed,
        "bundled_native_content_identical": native_a == native_b,
        "projection_and_gdal_resources_identical": resources_a == resources_b,
        "independent_source_attestation": False,
        "bitwise_reproducible_wheel_proven": False,
        "build_root_cause_verified": False,
        "license_review": "REQUIRED",
        "ha_installation": "BLOCKED",
        "opera_activation": "BLOCKED",
    }

def main(argv):
    if len(argv) != 3:
        print("usage: compare_opera_native_inventories.py OLD_JSON NEW_JSON", file=sys.stderr)
        return 2
    try:
        result = compare(argv[1], argv[2])
    except (ValueError, OSError, UnicodeError, TypeError):
        print("F7 inventory comparison rejected", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
