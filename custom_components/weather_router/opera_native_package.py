"""F7 optional native package admission. Dormant: never installs or imports rasterio.

The inventory is a *candidate* gate, not an HA loader or deployment approval.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile

WHEEL_NAME = "rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl"
MAX_WHEEL_BYTES = 250 * 1024 * 1024
MAX_MEMBERS = 10000
MAX_UNCOMPRESSED_BYTES = 700 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_REQUIRED = ("rasterio/proj_data/proj.db", "rasterio/gdal_data/gdalvrt.xsd")


class NativePackageRejected(ValueError):
    """A package is not suitable for *consideration* as an optional native dependency."""


def inspect_candidate(wheel_path: str | Path, expected_sha256: str) -> dict:
    """Read-only ZIP admission; no extraction, sys.path or environment changes.

    A pass never authorizes install/registration. Licensing/SBOM must be checked
    separately. Caller supplies SHA256 from a *trusted* independently verified
    provenance record, not from the package itself.
    """
    path = Path(wheel_path)
    if not _HASH.fullmatch(expected_sha256):
        raise NativePackageRejected("untrusted_digest")
    if path.name != WHEEL_NAME or not path.is_file() or path.is_symlink():
        raise NativePackageRejected("wheel_name_or_path")
    size = path.stat().st_size
    if not 0 < size <= MAX_WHEEL_BYTES:
        raise NativePackageRejected("wheel_size")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected_sha256:
        raise NativePackageRejected("wheel_sha256_mismatch")
    try:
        with ZipFile(path) as wheel:
            members = wheel.infolist()
            if len(members) > MAX_MEMBERS:
                raise NativePackageRejected("member_count")
            total = 0
            names = set()
            for item in members:
                name = item.filename
                if (name.startswith("/") or "\\" in name or
                        any(part in (".", "..", "") for part in name.rstrip("/").split("/"))):
                    raise NativePackageRejected("unsafe_member")
                if name in names:
                    raise NativePackageRejected("duplicate_member")
                names.add(name)
                # Reject ZIP symlinks and other Unix non-regular members.
                kind = (item.external_attr >> 16) & 0o170000
                if kind not in (0, 0o100000, 0o040000):
                    raise NativePackageRejected("unsafe_file_type")
                if item.compress_size and item.file_size > max(100 * item.compress_size, 16 * 1024 * 1024):
                    raise NativePackageRejected("suspicious_compression_ratio")
                total += item.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise NativePackageRejected("uncompressed_limit")
            if not all(any(n.endswith(suffix) for n in names) for suffix in _REQUIRED):
                raise NativePackageRejected("missing_projection_data")
            if not any("libgdal" in n.lower() and ".so" in n for n in names):
                raise NativePackageRejected("missing_gdal")
            if not any("libproj" in n.lower() and ".so" in n for n in names):
                raise NativePackageRejected("missing_proj")
            metadata = [n for n in names if n == "rasterio-1.5.2.dist-info/WHEEL"]
            if len(metadata) != 1:
                raise NativePackageRejected("wheel_metadata")
            wheel_text = wheel.read(metadata[0]).decode("utf-8")
            if "Tag: cp314-cp314-musllinux_1_2_x86_64" not in wheel_text.splitlines():
                raise NativePackageRejected("wheel_tag")
    except (BadZipFile, OSError, UnicodeError, RuntimeError) as exc:
        raise NativePackageRejected("broken_wheel") from exc
    return {"status": "candidate_inventory_pass_not_installable",
            "sha256": digest.hexdigest(), "wheel_bytes": size,
            "members": len(members), "uncompressed_bytes": total}


def optional_runtime_status() -> dict:
    """Diagnostic only; do not import GDAL, alter global import paths, or enable OPERA."""
    from importlib.util import find_spec
    try:
        found = find_spec("rasterio") is not None
    except (ImportError, ValueError):
        found = False
    return {"opera_native_enabled": False, "rasterio_discoverable": found,
            "reason": "provider_and_http_activation_blocked"}
