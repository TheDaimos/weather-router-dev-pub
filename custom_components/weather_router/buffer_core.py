"""E-078 isolated memory buffer. NOT wired into the WeatherRouter data path.

All calls are opt-in, fail-closed and require validated external authorization.
Provider operation permissions and upstream quotas remain outside this component.
No disk writes, background tasks, network, or Home Assistant imports.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Any, Callable, Hashable

MAX_ENTRIES = 256
MAX_BYTES = 16 * 1024 * 1024
MAX_TTL = 3600


@dataclass(frozen=True)
class BufferPolicy:
    """Effective, validated caching rights for one specific request."""
    allow_write: bool = False
    allow_serve: bool = False
    allow_prefetch: bool = False
    ttl_seconds: int = 0


def validate_policy(value: Any) -> BufferPolicy:
    if not isinstance(value, BufferPolicy):
        raise ValueError("invalid buffer policy")
    if (type(value.allow_write) is not bool
            or type(value.allow_serve) is not bool
            or type(value.allow_prefetch) is not bool
            or type(value.ttl_seconds) is not int
            or not 0 <= value.ttl_seconds <= MAX_TTL):
        raise ValueError("invalid buffer policy fields")
    return value


class IsolatedBuffer:
    """Bounded buffer; master switch defaults OFF and clearing is immediate."""

    def __init__(self, *, max_entries: int = MAX_ENTRIES,
                 max_bytes: int = MAX_BYTES,
                 clock: Callable[[], float] = monotonic) -> None:
        if (type(max_entries) is not int or not 1 <= max_entries <= MAX_ENTRIES
                or type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES):
            raise ValueError("invalid resource cap")
        self._enabled = False
        self._entries: OrderedDict[Hashable, tuple[bytes, float]] = OrderedDict()
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._clock = clock
        self._bytes = 0
        self._hits = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if not enabled:
            self.clear()
        self._enabled = enabled

    def clear(self) -> None:
        self._entries.clear()
        self._bytes = 0

    def _remove(self, key: Hashable) -> None:
        current = self._entries.pop(key, None)
        if current is not None:
            self._bytes -= len(current[0])

    def _purge(self) -> None:
        now = self._clock()
        for key, (_, deadline) in list(self._entries.items()):
            if deadline <= now:
                self._remove(key)

    def write(self, key: Hashable, data: bytes, *, policy: BufferPolicy,
              authorized: bool, prefetch: bool = False) -> bool:
        if not self._enabled or authorized is not True:
            return False
        try:
            rule = validate_policy(policy)
        except ValueError:
            return False
        if (not rule.allow_write or (prefetch and not rule.allow_prefetch)
                or rule.ttl_seconds == 0 or type(data) is not bytes
                or not data or len(data) > self._max_bytes):
            return False
        self._purge()
        self._remove(key)
        while (self._entries and
               (len(self._entries) >= self._max_entries
                or self._bytes + len(data) > self._max_bytes)):
            self._remove(next(iter(self._entries)))
        self._entries[key] = (data, self._clock() + rule.ttl_seconds)
        self._bytes += len(data)
        return True

    def read(self, key: Hashable, *, policy: BufferPolicy,
             authorized: bool) -> bytes | None:
        if not self._enabled or authorized is not True:
            return None
        try:
            rule = validate_policy(policy)
        except ValueError:
            return None
        if not rule.allow_serve:
            return None
        self._purge()
        item = self._entries.get(key)
        if item is None:
            return None
        self._entries.move_to_end(key)
        self._hits += 1
        return item[0]

    def stats(self) -> dict[str, int | bool]:
        self._purge()
        return {"enabled": self._enabled, "entries": len(self._entries),
                "bytes": self._bytes, "hits": self._hits}
