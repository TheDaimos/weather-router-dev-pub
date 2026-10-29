"""Fail-closed durable OPERA cycle journal; never authorizes a radar tile.

Committed frames are copied into a private directory and verified again on
inspection. Recovery returns metadata only: it cannot restore scientific
approval, palette, HTTP authorization, or provider/service enablement.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import tempfile
import fcntl
from contextlib import contextmanager

PRODUCTS = {"RATE", "DBZH"}
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SCHEMA = "weather_router.opera.cycle_journal.v1"
MAX_BYTES = 12 * 1024 * 1024


class CycleStoreError(ValueError):
    pass


class CycleJournal:
    def __init__(self, root, *, max_disk_bytes=32 * 1024 * 1024):
        if type(max_disk_bytes) is not int or not 2 * MAX_BYTES <= max_disk_bytes <= 256 * 1024 * 1024:
            raise CycleStoreError('invalid_journal_quota')
        self.max_disk_bytes = max_disk_bytes
        self.root = Path(root).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.path = self.root / "active.json"
        self.lock_path = self.root / ".journal.lock"

    def _atomic_bytes(self, dest, payload):
        fd, name = tempfile.mkstemp(prefix=".opera-stage-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(name, 0o600)
            os.replace(name, dest)
            if hasattr(os, "O_DIRECTORY"):
                dfd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
        finally:
            Path(name).unlink(missing_ok=True)

    @contextmanager
    def _writer_lock(self):
        """Advisory cross-process Linux lock for all journal mutations."""
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _clean_unreferenced_locked(self, live):
        """Clean only journal-owned files; never touch live frame-reader cache."""
        for file in self.root.iterdir():
            if file.is_symlink():
                continue
            if file.name.startswith(".opera-stage-") or (
                re.fullmatch(r"(?:RATE|DBZH)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{64}[.]bin", file.name)
                and file.name not in live
            ):
                if file.is_file():
                    file.unlink()

    def cleanup(self):
        with self._writer_lock():
            records = self.inspect()  # Bad manifest -> no deletion.
            self._clean_unreferenced_locked({v["file"] for v in records.values()})

    def disk_usage(self):
        """Journal-owned physical bytes only (no secrets/paths)."""
        return sum(p.stat().st_size for p in self.root.iterdir()
                   if p.is_file() and not p.is_symlink() and
                   (p == self.path or p.name.startswith(".opera-stage-") or
                    re.fullmatch(r"(?:RATE|DBZH)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{64}[.]bin", p.name)))

    def commit(self, frame, attribution, *, previous=None):
        with self._writer_lock():
            return self._commit_locked(frame, attribution, previous=previous)

    def _commit_locked(self, frame, attribution, *, previous=None):
        if (frame.product not in PRODUCTS
                or not isinstance(frame.valid_at, datetime) or frame.valid_at.tzinfo is None
                or not isinstance(frame.digest, str) or DIGEST.fullmatch(frame.digest) is None
                or not isinstance(attribution, str) or not attribution.strip()):
            raise CycleStoreError("invalid_cycle_metadata")
        source = Path(frame.path)
        if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= MAX_BYTES:
            raise CycleStoreError("untrusted_frame")
        payload = source.read_bytes()
        if sha256(payload).hexdigest() != frame.digest or len(payload) != frame.byte_size:
            raise CycleStoreError("frame_digest_mismatch")
        stamp = frame.valid_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"{frame.product}-{stamp}-{frame.digest}.bin"
        old = self.inspect()
        if previous is not None and previous != old:
            raise CycleStoreError("journal_changed")
        prior = old.get(frame.product)
        if prior is not None:
            if stamp < prior["generation"]:
                raise CycleStoreError("persistent_cycle_rollback")
            if stamp == prior["generation"] and frame.digest != prior["sha256"]:
                raise CycleStoreError("persistent_cycle_conflict")
        new = dict(old)
        new[frame.product] = {
            "product": frame.product, "valid_at": frame.valid_at.astimezone(timezone.utc).isoformat(),
            "generation": stamp, "sha256": frame.digest, "bytes": frame.byte_size,
            "file": name, "attribution": attribution,
            "integrity": "sha256_verified", "publication": "journaled_not_authorized",
        }
        # Bound even in-flight transactions to at most one new frame beyond
        # the active committed set. Never evict the active manifest to fit.
        live_names = {v["file"] for v in old.values()}
        self._clean_unreferenced_locked(live_names)
        active_bytes = sum(v["bytes"] for v in old.values())
        if active_bytes + len(payload) > self.max_disk_bytes:
            raise CycleStoreError("journal_quota_exceeded")
        self._atomic_bytes(self.root / name, payload)
        document = {"schema": SCHEMA, "cycles": new}
        self._atomic_bytes(self.path, json.dumps(document, sort_keys=True, separators=(",", ":")).encode())
        self._clean_unreferenced_locked({v["file"] for v in new.values()})
        return new[frame.product]

    def inspect(self):
        """Validate all published records. Broken journals fail closed."""
        if not self.path.exists():
            return {}
        try:
            raw = self.path.read_bytes()
            if len(raw) > 16384:
                raise CycleStoreError("oversized_manifest")
            obj = json.loads(raw)
            if obj.get("schema") != SCHEMA or not isinstance(obj.get("cycles"), dict):
                raise CycleStoreError("invalid_manifest")
            records = obj["cycles"]
            for product, item in records.items():
                if product not in PRODUCTS or not isinstance(item, dict):
                    raise CycleStoreError("invalid_product")
                digest = item["sha256"]
                if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
                    raise CycleStoreError("invalid_digest")
                stamp = item["generation"]
                date = datetime.fromisoformat(item["valid_at"])
                if (date.tzinfo is None or date.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") != stamp
                        or item["product"] != product or item["file"] != f"{product}-{stamp}-{digest}.bin"):
                    raise CycleStoreError("invalid_identity")
                name = item["file"]
                path = self.root / name
                if path.is_symlink() or not path.is_file():
                    raise CycleStoreError("missing_frame")
                data = path.read_bytes()
                if (not 0 < len(data) <= MAX_BYTES or len(data) != item["bytes"]
                        or sha256(data).hexdigest() != digest):
                    raise CycleStoreError("integrity_failure")
                if item.get("publication") != "journaled_not_authorized":
                    raise CycleStoreError("unexpected_authorization")
            return records
        except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
            raise CycleStoreError("recovery_blocked") from exc

    def recover_metadata(self, *, now=None, max_age_seconds=1500,
                         provider_enabled=False, services=None):
        """Report valid metadata, never publish it as HTTP/Consumer frames."""
        from .opera_runtime import utc_status
        records = self.inspect()
        result = {}
        for product, item in records.items():
            valid = datetime.fromisoformat(item["valid_at"])
            status = utc_status(valid, now=now, max_age_seconds=max_age_seconds)
            result[product] = {
                "generation": item["generation"], "utc_status": status,
                "integrity": item["integrity"], "authorized": False,
                "provider_requested": provider_enabled is True,
                "service_requested": (services or {}).get(product) is True,
            }
        return result
