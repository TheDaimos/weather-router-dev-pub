"""F7: read-only section-level differential of two disposable CP314 source wheels.

Both inputs are unsigned source-build *candidates*. Compare bytes without
importing ELF modules or extracting archive members. Never treats identical
outputs as legal, security, provenance, or Home Assistant installation approval.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from zipfile import ZipFile, BadZipFile

MAX_WHEEL_BYTES = 120 * 1024 * 1024
MAX_EXTENSION_BYTES = 48 * 1024 * 1024
WHEEL_NAME = re.compile(r"rasterio-1\.5\.2-cp314-cp314-linux_x86_64\.whl\Z")
ELF_NAME = re.compile(r"rasterio/[^/]+\.cpython-314-x86_64-linux-musl\.so\Z")

def _wheel(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= MAX_WHEEL_BYTES:
        raise ValueError("untrusted_wheel_path")
    if not WHEEL_NAME.fullmatch(p.name):
        raise ValueError("wrong_wheel_name")
    h = hashlib.sha256()
    with p.open("rb") as stream:
        for part in iter(lambda: stream.read(65536), b""):
            h.update(part)
    members = {}
    with ZipFile(p) as archive:
        names = [m.filename for m in archive.infolist()]
        if len(names) != len(set(names)):
            raise ValueError("duplicate_zip_entry")
        for member in archive.infolist():
            if not ELF_NAME.fullmatch(member.filename):
                continue
            if not 0 < member.file_size <= MAX_EXTENSION_BYTES:
                raise ValueError("oversize_native_extension")
            with archive.open(member) as stream:
                raw = stream.read(MAX_EXTENSION_BYTES + 1)
            if len(raw) != member.file_size or not raw.startswith(b"\x7fELF"):
                raise ValueError("invalid_native_extension")
            members[member.filename] = raw
    if not members:
        raise ValueError("no_native_extensions")
    return {"sha256": h.hexdigest(), "size_bytes": p.stat().st_size}, members

def _sections(data):
    """Bounded strict ELF64 little-endian x86-64 SHT reader, no ELF execution."""
    if (len(data) < 64 or data[:6] != b"\x7fELF\x02\x01"
            or struct.unpack_from("<H", data, 18)[0] != 62):
        raise ValueError("unsupported_elf")
    shoff = struct.unpack_from("<Q", data, 40)[0]
    entsize, n, names_idx = struct.unpack_from("<HHH", data, 58)
    if (not 0 < n <= 512 or entsize < 64 or names_idx >= n
            or shoff > len(data) or n * entsize > len(data) - shoff):
        raise ValueError("invalid_elf_section_table")
    records = []
    for i in range(n):
        off = shoff + i * entsize
        name, stype, _, _, start, size, _, _, _, _ = struct.unpack_from(
            "<IIQQQQIIQQ", data, off)
        if start > len(data) or (stype != 8 and size > len(data) - start):
            raise ValueError("invalid_elf_section_range")
        records.append((name, stype, start, size))
    _, stype, offset, size = records[names_idx]
    if stype != 3 or not 0 < size <= 65536:
        raise ValueError("invalid_elf_section_names")
    name_bytes = data[offset:offset + size]
    result = {}
    for idx, (str_offset, stype, start, size) in enumerate(records):
        if str_offset >= len(name_bytes):
            raise ValueError("invalid_section_name")
        end = name_bytes.find(b"\0", str_offset)
        if end == -1:
            raise ValueError("unterminated_section_name")
        name = name_bytes[str_offset:end].decode("ascii", errors="replace")
        # NOBITS sections occupy no file bytes.
        if stype == 8 or not size:
            continue
        label = name if name else f"unnamed_section_{idx}"
        if label in result:
            raise ValueError("duplicate_elf_section_name")
        result[label] = (start, size)
    return result

def _elf_diff(old, new):
    a, b = _sections(old), _sections(new)
    if len(old) != len(new):
        return {"same_size": False, "changed_sections": None,
                "different_bytes": None, "gnu_build_id_note_only": False}
    names = sorted(set(a) | set(b))
    changed = []
    for n in names:
        ar, br = a.get(n), b.get(n)
        if ar != br or (ar and old[ar[0]:ar[0] + ar[1]] != new[br[0]:br[0] + br[1]]):
            changed.append(n)
    bytes_diff = sum(x != y for x, y in zip(old, new))
    left, right = bytearray(old), bytearray(new)
    for target, records in ((left, a), (right, b)):
        if ".note.gnu.build-id" in records:
            start, size = records[".note.gnu.build-id"]
            target[start:start + size] = b"\0" * size
    return {"same_size": True, "changed_sections": changed,
            "different_bytes": bytes_diff,
            "gnu_build_id_note_only": old != new and left == right}

def compare(left, right):
    old, old_modules = _wheel(left)
    new, new_modules = _wheel(right)
    if set(old_modules) != set(new_modules):
        raise ValueError("extension_member_mismatch")
    modules = []
    for name in sorted(old_modules):
        a, b = old_modules[name], new_modules[name]
        row = {"module": name, "old_sha256": hashlib.sha256(a).hexdigest(),
               "new_sha256": hashlib.sha256(b).hexdigest(),
               "old_bytes": len(a), "new_bytes": len(b),
               "identical": a == b}
        row.update(_elf_diff(a, b))
        modules.append(row)
    changed = [x for x in modules if not x["identical"]]
    return {
        "schema": "weather_router.f7.raw_elf_drift_probe.v1",
        "status": "DIAGNOSTIC_ONLY_NOT_DISTRIBUTABLE",
        "left_raw_wheel": old, "right_raw_wheel": new,
        "extensions_count": len(modules),
        "changed_extensions": len(changed),
        "unchanged_extensions": len(modules) - len(changed),
        "changed_sections_by_extension": modules,
        "same_source_version_but_tarball_sha_independently_verified": False,
        "build_inputs_attested": False, "wheel_reproducibility_proven": False,
        "root_cause_proven": False, "license_cleared": False,
        "ha_installation": "BLOCKED", "opera_activation": "BLOCKED"
    }

def main(argv):
    if len(argv) != 3:
        print("usage: probe_opera_raw_elf_drift.py OLD_RAW_WHEEL NEW_RAW_WHEEL", file=sys.stderr)
        return 2
    try:
        report = compare(argv[1], argv[2])
    except (ValueError, OSError, BadZipFile, UnicodeError, TypeError, struct.error):
        print("F7 raw ELF differential rejected", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
