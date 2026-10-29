"""F7 offline provenance envelope for an unapproved CP314-musl wheel candidate.

The envelope cryptographically binds *bytes* of all build evidence to the wheel
SHA256. It is NOT signed, and its own hashes NEVER confer independent trust.
Standard library only. No imports or operations on native wheel binaries.
"""
from __future__ import annotations
import hashlib
import json
import re
import sys
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_FILE = 4 * 1024 * 1024
FILES = ("f7-native-inventory.json", "f7-native-apk-license-candidates.json",
         "f7-build-inputs-unapproved.json", "f7-cyclonedx-unapproved.json",
         "f7-sbom-quality-unapproved.json", "f7-secdb-candidates-unapproved.json")
SCHEMA = "weather_router.f7.provenance_envelope.v1"

def _read(root: Path, name: str):
    p = root / name
    if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= MAX_FILE:
        raise ValueError("missing_or_oversized_evidence:" + name)
    raw = p.read_bytes()
    if len(raw) > MAX_FILE:
        raise ValueError("oversized_evidence")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()

def build(root: Path):
    root = Path(root)
    docs = {}
    hashes = {}
    for name in FILES:
        docs[name], hashes[name] = _read(root, name)
    inv = docs[FILES[0]]
    attr = docs[FILES[1]]
    build = docs[FILES[2]]
    bom = docs[FILES[3]]
    quality = docs[FILES[4]]
    secdb = docs[FILES[5]]
    if inv.get("schema") != "weather_router.f7.native_candidate_inventory.v2" or inv.get("status") != "UNAPPROVED_NOT_DISTRIBUTABLE":
        raise ValueError("inventory_not_unapproved")
    wheel = inv.get("candidate", {}).get("sha256")
    if not isinstance(wheel, str) or not SHA.fullmatch(wheel):
        raise ValueError("wheel_digest_invalid")
    if any(d.get("wheel_sha256") != wheel for d in (attr, build, quality)):
        raise ValueError("evidence_not_bound_to_wheel")
    if len(inv.get("files", [])) != inv.get("files_count") or inv.get("native_elf_count") != 101:
        raise ValueError("native_inventory_incomplete")
    if attr.get("native_elf_count") != 101 or quality.get("elf_included") != 101:
        raise ValueError("native_component_count_mismatch")
    if bom.get("bomFormat") != "CycloneDX" or len(bom.get("components", [])) != 101:
        raise ValueError("sbom_missing_native_members")
    # All 101 file digests must have a matching native BOM entry.
    native = {e["path"]:e["sha256"] for e in inv["files"] if e.get("elf_magic") is True}
    actual = {}
    for e in bom["components"]:
        h = [x["content"] for x in e.get("hashes", []) if x.get("alg") == "SHA-256"]
        if e.get("name") in actual or len(h) != 1:
            raise ValueError("sbom_duplicate_or_unhashed_native")
        actual[e["name"]] = h[0]
    if native != actual:
        raise ValueError("sbom_file_digests_mismatch")
    if secdb.get("ha_installation") != "BLOCKED":
        raise ValueError("security_gate_not_closed")
    image = build.get("container_image_digest")
    if not isinstance(image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise ValueError("image_digest_unavailable")
    if build.get("ha_installation") != "BLOCKED":
        raise ValueError("build_gate_not_closed")
    return {
        "schema": SCHEMA,
        "candidate": {
            "name":"rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl",
            "sha256":wheel, "abi":"cp314-cp314-musllinux_1_2_x86_64",
            "rasterio":"1.5.2","gdal":"3.13.3","proj":"9.8.1"},
        "base_image_digest":image,
        "evidence_file_sha256":dict(sorted(hashes.items())),
        "native_elf_count":101,
        "signature_envelope": {
            "payload_canonicalization":"RFC8785_NOT_IMPLEMENTED",
            "signing_profile":"external_offline_ed25519_pending",
            "trusted_public_key_id":None,"signature_base64":None,
            "independent_signature_verified":False},
        "source_archive_signature_verified":False,
        "apk_archive_hashes_independently_verified":False,
        "license_review_complete":False,"security_review_complete":False,
        "status":"BOUND_UNAPPROVED_EVIDENCE_ONLY",
        "binary_distribution":"BLOCKED","ha_installation":"BLOCKED",
        "opera_activation":"BLOCKED",
    }

def main(args):
    if len(args) != 3:
        print("usage: f7_provenance_envelope.py EVIDENCE_DIRECTORY OUTPUT_JSON",file=sys.stderr)
        return 2
    try:
        result=build(Path(args[1]))
        target=Path(args[2])
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError("unsafe_output")
        target.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    except (ValueError,KeyError,TypeError,OSError,UnicodeError):
        print("F7 unsigned provenance binding rejected",file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
