"""Bounded verified source-frame cache. Dormant: no route or provider registration."""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import RLock
import os
import re
import shutil
import tempfile

MAX_SOURCE_BYTES = 12 * 1024 * 1024

class FrameCacheError(ValueError):
    pass

@dataclass(frozen=True)
class VerifiedFrame:
    product: str
    valid_at: datetime
    digest: str
    path: Path
    byte_size: int

class ImmutableFrameCache:
    """Copy accepted bytes once to private storage, never trust mutable original.

    This does not authorize freshness, provider, user or downstream tile HTTP.
    """
    def __init__(self, *, max_frames=3, max_bytes=24 * 1024 * 1024):
        if (type(max_frames) is not int or not 1 <= max_frames <= 16
                or type(max_bytes) is not int
                or not MAX_SOURCE_BYTES <= max_bytes <= 256 * 1024 * 1024):
            raise FrameCacheError("invalid_limits")
        self._folder = Path(tempfile.mkdtemp(prefix="wr-opera-"))
        os.chmod(self._folder, 0o700)
        self._max_frames, self._max_bytes = max_frames, max_bytes
        self._frames = OrderedDict()
        self._lock = RLock()
        self.hash_operations = 0

    def admit(self, *, source_path, product, valid_at, expected_sha256):
        if (product not in ("DBZH", "RATE")
                or not isinstance(valid_at, datetime) or valid_at.tzinfo is None):
            raise FrameCacheError("invalid_product_or_time")
        if not isinstance(expected_sha256, str) or not re.fullmatch("[a-f0-9]{64}", expected_sha256):
            raise FrameCacheError("invalid_digest")
        t = valid_at.astimezone(timezone.utc)
        key = (product, t.isoformat(), expected_sha256)
        with self._lock:
            if key in self._frames:
                self._frames.move_to_end(key)
                return self._frames[key]
            source = Path(source_path)
            if not source.is_file() or source.is_symlink() or not 0 < source.stat().st_size <= MAX_SOURCE_BYTES:
                raise FrameCacheError("invalid_file")
            fd, temp = tempfile.mkstemp(prefix="staging-", dir=self._folder)
            size, digest = 0, sha256()
            try:
                with os.fdopen(fd, "wb") as out, source.open("rb") as incoming:
                    while block := incoming.read(65536):
                        size += len(block)
                        if size > MAX_SOURCE_BYTES or size > self._max_bytes:
                            raise FrameCacheError("source_too_large")
                        digest.update(block)
                        out.write(block)
                self.hash_operations += 1
                if digest.hexdigest() != expected_sha256:
                    raise FrameCacheError("digest_mismatch")
                dest = self._folder / (expected_sha256 + ".tiff")
                os.replace(temp, dest)
                os.chmod(dest, 0o400)
                frame = VerifiedFrame(product, t, expected_sha256, dest, size)
                self._frames[key] = frame
                while (len(self._frames) > self._max_frames
                       or sum(v.byte_size for v in self._frames.values()) > self._max_bytes):
                    _, old = self._frames.popitem(last=False)
                    if old.path != dest and not any(v.path == old.path for v in self._frames.values()):
                        old.path.unlink(missing_ok=True)
                return frame
            finally:
                Path(temp).unlink(missing_ok=True)

    def get(self, *, product, valid_at, digest):
        if not isinstance(valid_at, datetime) or valid_at.tzinfo is None:
            raise FrameCacheError("missing_timezone")
        key = (product, valid_at.astimezone(timezone.utc).isoformat(), digest)
        with self._lock:
            frame = self._frames.get(key)
            if frame:
                self._frames.move_to_end(key)
            return frame

    def close(self):
        with self._lock:
            self._frames.clear()
            shutil.rmtree(self._folder, ignore_errors=True)
