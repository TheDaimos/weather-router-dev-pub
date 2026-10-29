"""F7 CI-only ELF dynamic-section and transformation observability, NOT a replay.

Originals and wheel bytes are read in isolated CI. Readelf examines disposable
temporary files; the comparator neither patches nor installs ELF code.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zipfile import ZipFile

HEX = re.compile(r"[a-f0-9]{64}\Z")
DYNAMIC = re.compile(r"\((NEEDED|SONAME|RPATH|RUNPATH)\).*?\[(.*?)\]")
MAX_ELF = 70 * 1024 * 1024

def sha(b):
    return hashlib.sha256(b).hexdigest()

def dynamics(data):
    if not data.startswith(b"\x7fELF") or len(data) > MAX_ELF:
        raise ValueError("invalid_elf")
    with tempfile.TemporaryDirectory(prefix="f7-elf-observe-") as t:
        p = Path(t) / "object.elf"
        p.write_bytes(data)
        run = subprocess.run(["readelf", "-d", str(p)], capture_output=True,
                             text=True, timeout=15, check=False)
        if run.returncode:
            return {"readelf_status": "UNAVAILABLE_OR_UNSUPPORTED", "fields": None}
        d = {"NEEDED": [], "SONAME": [], "RPATH": [], "RUNPATH": []}
        for kind, value in DYNAMIC.findall(run.stdout):
            d[kind].append(value)
        return {"readelf_status": "OBSERVED_NOT_ATTESTED",
                "fields": {k: sorted(v) for k, v in d.items()}}

def inspect(report, wheelpath, root=Path("/")):
    if (report.get("schema") != "weather_router.f7.apk_embedded_binary_comparison.v1"
            or report.get("native_elf_count") != 101
            or len(report.get("elf_components", [])) != 101):
        raise ValueError("wrong_report")
    wheelpath = Path(wheelpath)
    if wheelpath.is_symlink() or not wheelpath.is_file():
        raise ValueError("wheel_path")
    if not HEX.fullmatch(report.get("wheel_sha256", "")):
        raise ValueError("wheel_digest")
    if sha(wheelpath.read_bytes()) != report["wheel_sha256"]:
        raise ValueError("wheel_digest_mismatch")
    results = []
    with ZipFile(wheelpath) as z:
        for row in report["elf_components"]:
            name = row["wheel_path"]
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("unsafe_name")
            if z.getinfo(name).file_size > MAX_ELF:
                raise ValueError("oversized_member")
            target = z.read(name)
            if sha(target) != row["wheel_sha256"]:
                raise ValueError("wheel_member_mismatch")
            srcname = row.get("original_resolved_path")
            original = None
            if srcname:
                p = root / srcname
                resolved = p.resolve()
                if (not resolved.is_relative_to(root.resolve()) or
                        not resolved.is_file() or resolved.stat().st_size > MAX_ELF):
                    raise ValueError("unsafe_origin")
                original = resolved.read_bytes()
                if sha(original) != row.get("original_installed_sha256"):
                    raise ValueError("original_sha_mismatch")
            before = dynamics(original) if original else None
            after = dynamics(target)
            b = before["fields"] if before else None
            a = after["fields"]
            changes = {k: {"before": b[k], "after": a[k]}
                       for k in ("NEEDED", "SONAME", "RPATH", "RUNPATH")
                       if b is not None and a is not None and b[k] != a[k]}
            results.append({"wheel_path": name, "original_path": srcname,
                            "original_sha256": sha(original) if original else None,
                            "wheel_sha256": sha(target), "before": before,
                            "after": after, "dynamic_changes": changes,
                            "transformation_replayed": False})
    return {"schema": "weather_router.f7.elf_dynamic_transform_observation.v1",
            "wheel_sha256": report["wheel_sha256"],
            "total": len(results), "originals_observed": sum(x["before"] is not None for x in results),
            "changed_dynamic_count": sum(bool(x["dynamic_changes"]) for x in results),
            "records": results, "replay_verified": False,
            "independent_provenance_verified": False, "distribution": "BLOCKED",
            "ha_installation": "BLOCKED", "opera_activation": "BLOCKED"}

def main(argv):
    if len(argv) != 4:
        return 2
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("WR_OPERA_ISOLATED_CI") != "1":
        print("isolated CI only", file=sys.stderr)
        return 2
    try:
        report = json.loads(Path(argv[1]).read_text())
        out = inspect(report, argv[2])
        Path(argv[3]).write_text(json.dumps(out, sort_keys=True, indent=2) + "\n")
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print("F7 ELF observation rejected:", str(exc), file=sys.stderr)
        return 1
    print("F7 ELF DYNAMIC OBSERVATION:", out["total"], "ELF files,",
          out["originals_observed"], "installed sources, not replay-approved")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
