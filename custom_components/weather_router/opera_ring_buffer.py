"""Opt-in, executor-only persistent OPERA original-file ring buffer.

Pure Python file store: never invoked on Home Assistant's event loop. No HTTP
authorization, scientific approval or automatic network fetch is provided.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"
STAMP = re.compile(r"^20\d{6}T\d{6}Z$")
MAX_ORIGINAL = 12 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024


def _utc(stamp: str) -> datetime:
    if not isinstance(stamp, str) or not STAMP.fullmatch(stamp):
        raise ValueError("invalid_utc_stamp")
    try:
        dt = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("invalid_utc_stamp") from exc
    if dt.strftime("%Y%m%dT%H%M%SZ") != stamp:
        raise ValueError("invalid_utc_stamp")
    return dt


class OperaRingBuffer:
    """Owned, bounded original-file store; use only through an HA executor."""

    def __init__(self, root: Path, *, hours: int = 6, limit_bytes: int = MAX_TOTAL):
        if type(hours) is not int or not 1 <= hours <= 48:
            raise ValueError("invalid_retention")
        if type(limit_bytes) is not int or not MAX_ORIGINAL <= limit_bytes <= MAX_TOTAL:
            raise ValueError("invalid_capacity")
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("unsafe_root")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("unsafe_root")
        self.hours, self.limit_bytes = hours, limit_bytes
        self._lock = RLock()
        self._active_readers = 0

    @contextmanager
    def read_frame(self, stamp: str):
        """Hold the writer/cleanup lock while a trusted executor reads an original."""
        _utc(stamp)
        with self._lock:
            path = self.root / f"RATE-{stamp}.h5"
            if path.is_symlink() or not path.is_file():
                raise FileNotFoundError("frame_unavailable")
            self._active_readers += 1
            try:
                yield path
            finally:
                self._active_readers -= 1

    def recover(self) -> dict:
        """Reconcile persistent originals without depending on journal metadata.

        Only abandoned temporary downloads with the exact owned filename form
        are removed. Valid originals are never purged by recovery.
        """
        with self._lock:
            removed_temporary = 0
            for path in self.root.glob(".opera-*.tmp"):
                if path.is_symlink() or not path.is_file():
                    continue
                if not re.fullmatch(r"\.opera-[0-9a-f]{32}\.tmp", path.name):
                    continue
                path.unlink()
                removed_temporary += 1
            removed_capacity = self._trim(datetime.now(timezone.utc), expire=False)
            originals = []
            for dt, path in self._items():
                digest = sha256()
                with path.open("rb") as stream:
                    if stream.read(8) != HDF5_MAGIC:
                        # Preserve suspect originals for manual investigation.
                        continue
                    digest.update(HDF5_MAGIC)
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                originals.append({
                    "stamp": dt.strftime("%Y%m%dT%H%M%SZ"),
                    "sha256": digest.hexdigest(),
                    "bytes": self._size(path),
                })
            return {"originals": originals, "removed_temporary": removed_temporary,
                    "removed_capacity": removed_capacity,
                    "scientific_status": "UNVERIFIED"}

    def list_frames(self) -> list[dict]:
        """Safe historical metadata only; never expose filesystem paths."""
        with self._lock:
            return [
                {"stamp": dt.strftime("%Y%m%dT%H%M%SZ"),
                 "bytes": self._size(path),
                 "scientific_status": "UNVERIFIED"}
                for dt, path in self._items()
            ]

    def pin_verified_original(self, stamp: str) -> dict:
        """Atomically select, verify and copy one real RATE original under lock.

        No separately sampled catalog/hash is trusted as the snapshot identity.
        Never return file paths to the caller/browser.
        """
        _utc(stamp)
        with self.read_frame(stamp) as path:
            if path.is_symlink() or not path.is_file():
                raise ValueError("frame_not_found")
            size = self._size(path)
            if not 8 <= size <= MAX_ORIGINAL:
                raise ValueError("frame_size_invalid")
            with path.open("rb") as stream:
                raw = stream.read(MAX_ORIGINAL + 1)
            if len(raw) != size:
                raise ValueError("frame_read_incomplete")
            if raw[:8] != HDF5_MAGIC:
                raise ValueError("frame_hdf5_magic_invalid")
            return {"stamp": stamp, "sha256": sha256(raw).hexdigest(),
                    "bytes": size, "original": raw}

    def verified_frame_catalog(self) -> list[dict]:
        """Trusted, ordered on-disk inventory; not a raster/pixel approval.

        Only call from the Home Assistant executor. Do not return disk paths,
        original data or URL access permissions to the browser.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=self.hours)
            catalog = []
            for instant, path in self._items():
                if not cutoff <= instant <= now:
                    continue
                size = self._size(path)
                if not 8 <= size <= MAX_ORIGINAL:
                    continue
                digest = sha256()
                with path.open("rb") as stream:
                    if stream.read(8) != HDF5_MAGIC:
                        continue
                    digest.update(HDF5_MAGIC)
                    for chunk in iter(lambda: stream.read(65536), b""):
                        digest.update(chunk)
                catalog.append({
                    "stamp": instant.strftime("%Y%m%dT%H%M%SZ"),
                    "valid_at": instant.isoformat().replace("+00:00", "Z"),
                    "bytes": size,
                    "sha256": digest.hexdigest(),
                    "scientific_status": "UNVERIFIED",
                    "tile_authorized": False,
                    "historical": (now - instant).total_seconds() > 900,
                })
            return catalog

    def _items(self):
        items = []
        for path in self.root.glob("RATE-*.h5"):
            if path.is_symlink() or not path.is_file():
                continue
            stamp = path.name[5:-3]
            try:
                valid = _utc(stamp)
            except ValueError:
                continue
            items.append((valid, path))
        return sorted(items)

    def _size(self, path):
        if path.is_symlink() or not path.is_file():
            raise ValueError("unsafe_file")
        return path.stat().st_size

    def snapshot(self) -> dict:
        with self._lock:
            items = self._items()
            used = sum(self._size(p) for _, p in items)
            return {
                "count": len(items), "original_bytes": used,
                "original_mib": round(used / (1024 * 1024), 3),
                "capacity_bytes": self.limit_bytes,
                "retention_hours": self.hours,
                "automatic_cleanup_enabled": True,
                "utilization_percent": round(100 * used / self.limit_bytes, 2),
                "oldest_utc": items[0][0].isoformat().replace("+00:00", "Z") if items else None,
                "newest_utc": items[-1][0].isoformat().replace("+00:00", "Z") if items else None,
                "scientific_approved": False,
            }

    def _trim(self, now: datetime, *, expire=True):
        cutoff = now - timedelta(hours=self.hours)
        removed = 0
        for dt, path in self._items():
            if expire and dt < cutoff:
                path.unlink()
                removed += 1
        items = self._items()
        total = sum(self._size(p) for _, p in items)
        while total > self.limit_bytes and items:
            _, victim = items.pop(0)
            size = self._size(victim)
            victim.unlink()
            total -= size
            removed += 1
        return removed

    def cleanup(self, *, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("naive_datetime")
        with self._lock:
            return self._trim(now.astimezone(timezone.utc))

    def store(self, *, stamp: str, original: bytes, expected_sha256: str,
              now: datetime | None = None, validate_original=None):
        dt = _utc(stamp)
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("naive_datetime")
        if dt > now.astimezone(timezone.utc):
            raise ValueError("future_frame")
        if (not isinstance(original, bytes) or not 8 <= len(original) <= MAX_ORIGINAL
                or not original.startswith(HDF5_MAGIC)):
            raise ValueError("invalid_hdf5_original")
        # A trusted ODIM validator must inspect the complete original before disk admission.
        if not callable(validate_original):
            raise ValueError("odim_validation_required")
        digest = sha256(original).hexdigest()
        if digest != expected_sha256:
            raise ValueError("digest_mismatch")
        target = self.root / f"RATE-{stamp}.h5"
        with self._lock:
            if target.is_symlink():
                raise ValueError("unsafe_target")
            if target.exists():
                if self._size(target) == len(original) and sha256(target.read_bytes()).hexdigest() == digest:
                    self._trim(now.astimezone(timezone.utc))
                    return {"status": "duplicate" if target.exists() else "expired_by_policy", "sha256": digest}
                raise ValueError("conflicting_frame")
            temporary = self.root / (".opera-" + uuid4().hex + ".tmp")
            try:
                with temporary.open("xb") as stream:
                    os.chmod(temporary, 0o600)
                    stream.write(original)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Rehash persisted bytes before passing the owned file to HDF5.
                # A short write, file mutation or storage fault must fail closed.
                on_disk = sha256()
                with temporary.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        on_disk.update(chunk)
                if on_disk.hexdigest() != digest:
                    raise ValueError("persisted_digest_mismatch")
                # Inspector gets an owned temporary file and may raise to reject.
                checked = validate_original(temporary)
                if checked is not True:
                    raise ValueError("odim_validation_failed")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            self._trim(now.astimezone(timezone.utc))
            return {"status": "stored" if target.exists() else "expired_by_policy",
                    "sha256": digest}

    def clear(self, *, confirmed: bool = False):
        if confirmed is not True:
            raise PermissionError("confirmation_required")
        with self._lock:
            count = 0
            for _, path in self._items():
                path.unlink()
                count += 1
            return count
