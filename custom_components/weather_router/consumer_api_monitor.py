"""Bounded, opt-in, metadata-only recorder for WeatherRouter Consumer API calls."""
from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import json
import math
import re
from time import monotonic
from typing import Any
from uuid import uuid4

_SECRET_WORDS = ("token", "password", "secret", "authorization", "cookie", "credential", "apikey", "api_key", "private_key")
_COORDINATE_WORDS = ("latitude", "longitude", "lat", "lon", "bbox", "bounds", "viewport", "west", "east", "north", "south", "coordinates", "location")
_ALLOWED_RESULTS = frozenset({"success", "no_data", "rejected", "error", "timeout"})
_MAX_RECORDS = 250
_MAX_BYTES = 512 * 1024
_MAX_ENTRY_BYTES = 8192
_MAX_TTL_SECONDS = 3600


def _safe(value: Any, *, locations: bool = False, depth: int = 0) -> Any:
    """Discard secrets and bulky payloads; default-deny geolocation."""
    if depth >= 5:
        return "[depth-limited]"
    if isinstance(value, dict):
        safe = {}
        for key, item in list(value.items())[:80]:
            label = str(key)[:96]
            lower = label.lower()
            if any(word in lower for word in _SECRET_WORDS):
                safe[label] = "[redacted]"
            elif not locations and any(word == lower or lower.endswith("_" + word) for word in _COORDINATE_WORDS):
                safe[label] = "[location-redacted]"
            elif lower in {"data", "image", "tiles", "binary", "body", "raster", "payload", "base64"}:
                safe[label] = "[payload-omitted]"
            else:
                safe[label] = _safe(item, locations=locations, depth=depth + 1)
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe(v, locations=locations, depth=depth + 1) for v in value[:30]]
    if isinstance(value, str):
        if len(value) > 512:
            return "[large-text-omitted]"
        if "://" in value or re.search(r"(?i)(token|secret|password|api[_-]?key)\\s*[=:]", value):
            return "[sensitive-text-omitted]"
        return value
    if isinstance(value, float) and not math.isfinite(value):
        return "[non-finite-number]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[unsupported]"



def _providers_from_response(value: Any, *, limit: int = 12) -> list[str]:
    """Extract only provider identifiers, not data payloads."""
    found: list[str] = []
    def visit(node: Any, depth: int = 0) -> None:
        if depth > 4 or len(found) >= limit:
            return
        if isinstance(node, dict):
            for key in ("provider", "provider_id", "selected_provider", "source_provider"):
                value = node.get(key)
                if isinstance(value, str) and 0 < len(value) <= 128 and value not in found:
                    found.append(value)
            for key in ("sources", "layers", "selected", "provider", "routing"):
                child = node.get(key)
                if isinstance(child, (dict, list)):
                    visit(child, depth + 1)
        elif isinstance(node, list):
            for child in node[:limit]:
                visit(child, depth + 1)
    visit(value)
    return found[:limit]


class ConsumerApiMonitor:
    """Single-HA-process ring buffer: recording disabled until administrator opts in."""

    def __init__(self, *, max_records: int = _MAX_RECORDS, max_bytes: int = _MAX_BYTES,
                 ttl_seconds: int = _MAX_TTL_SECONDS) -> None:
        self.enabled = False
        self.allow_locations = False
        self.max_records = max(1, min(int(max_records), _MAX_RECORDS))
        self.max_bytes = max(1024, min(int(max_bytes), _MAX_BYTES))
        self.ttl_seconds = max(1, min(int(ttl_seconds), _MAX_TTL_SECONDS))
        self._rows: deque[tuple[float, dict[str, Any], int]] = deque()
        self._bytes = 0
        self.session_id = uuid4().hex

    def configure(self, *, enabled: bool, allow_locations: bool = False, clear: bool = False) -> None:
        if clear or (self.enabled and not enabled):
            self.clear()
        self.enabled = bool(enabled)
        self.allow_locations = bool(allow_locations) if self.enabled else False

    def clear(self) -> None:
        self._rows.clear()
        self._bytes = 0
        self.session_id = uuid4().hex

    def _prune(self) -> None:
        cutoff = monotonic() - self.ttl_seconds
        while self._rows and (self._rows[0][0] < cutoff or
                              len(self._rows) > self.max_records or
                              self._bytes > self.max_bytes):
            _, _, size = self._rows.popleft()
            self._bytes -= size

    def begin(self, *, api_version: str, command: str, message: dict[str, Any],
              user_id: str | None = None) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        now = datetime.now(UTC).isoformat()
        consumer = message.get("consumer_id", "unknown")
        if not isinstance(consumer, str) or not consumer or len(consumer) > 96:
            consumer = "unknown"
        correlation = message.get("correlation_id")
        if not isinstance(correlation, str) or len(correlation) > 128:
            correlation = None
        return {
            "request_id": uuid4().hex, "session_id": self.session_id,
            "api_version": api_version, "command": command,
            "consumer": consumer, "consumer_trusted": False,
            "connection_user": str(user_id)[:96] if user_id else None,
            "correlation_id": correlation, "capability": str(message.get("capability", ""))[:128],
            "profile": str(message.get("profile_id", ""))[:96] or None,
            "started_at": now, "_start": monotonic(),
            "request": _safe(message, locations=self.allow_locations),
        }

    def finish(self, token: dict[str, Any] | None, *, result: str,
               response: Any = None, error_code: str | None = None,
               providers: list[str] | None = None, routing: Any = None) -> None:
        if token is None or not self.enabled:
            return
        started = token.pop("_start", monotonic())
        token["ended_at"] = datetime.now(UTC).isoformat()
        token["duration_ms"] = round((monotonic() - started) * 1000, 2)
        token["result"] = result if result in _ALLOWED_RESULTS else "error"
        token["error_code"] = str(error_code)[:128] if error_code else None
        token["providers"] = [str(p)[:128] for p in (providers or [])[:12]]
        token["routing"] = _safe(routing, locations=self.allow_locations)
        token["response"] = _safe(response, locations=self.allow_locations)
        raw = json.dumps(token, ensure_ascii=False, allow_nan=False, default=str)
        size = len(raw.encode("utf-8"))
        if size > _MAX_ENTRY_BYTES:
            token["response"] = "[size-limited]"
            token["routing"] = "[size-limited]"
            token["request"] = "[size-limited]"
            raw = json.dumps(token, ensure_ascii=False)
            size = len(raw.encode("utf-8"))
        if size > _MAX_ENTRY_BYTES:
            return
        self._rows.append((monotonic(), token, size))
        self._bytes += size
        self._prune()

    def query(self, **filters: Any) -> dict[str, Any]:
        self._prune()
        records = [dict(row) for _, row, _ in self._rows]
        for key in ("api_version", "consumer", "command", "capability", "result", "correlation_id", "session_id"):
            val = filters.get(key)
            if val not in (None, "", "all"):
                records = [row for row in records if str(row.get(key, "")) == str(val)]
        provider = filters.get("provider")
        if provider:
            records = [row for row in records if provider in row.get("providers", [])]
        request_id = filters.get("request_id")
        if request_id:
            records = [row for row in records if row.get("request_id") == request_id]
        since, until = filters.get("since"), filters.get("until")
        if since:
            records = [row for row in records if row["started_at"] >= since]
        if until:
            records = [row for row in records if row["started_at"] <= until]
        minimum, maximum = filters.get("min_duration_ms"), filters.get("max_duration_ms")
        if minimum is not None:
            records = [r for r in records if r["duration_ms"] >= float(minimum)]
        if maximum is not None:
            records = [r for r in records if r["duration_ms"] <= float(maximum)]
        search = filters.get("search")
        if search:
            needle = str(search).lower()[:128]
            records = [r for r in records if needle in json.dumps(r, ensure_ascii=False).lower()]
        return {
            "schema": "weather_router.api_monitor.v1",
            "captured_at": datetime.now(UTC).isoformat(),
            "recording": self.enabled,
            "session_id": self.session_id,
            "record_count": len(records),
            "entries": records[-self.max_records:],
            "buffer_bytes": self._bytes,
        }

# The proxy observes boundary responses only; provider requests remain untouched.
_MONITOR_DATA_KEY = "weather_router_api_monitor"


def get_monitor(hass: Any) -> ConsumerApiMonitor:
    """Resolve recorder once per HA instance, not per consumer."""
    monitor = hass.data.get(_MONITOR_DATA_KEY)
    if monitor is None:
        monitor = ConsumerApiMonitor()
        hass.data[_MONITOR_DATA_KEY] = monitor
    return monitor


class MonitoredConnection:
    """Forward WebSocket traffic while recording only explicitly opted-in metadata."""

    def __init__(self, connection: Any, monitor: ConsumerApiMonitor,
                 msg: dict[str, Any], version: str) -> None:
        self._connection = connection
        self._monitor = monitor
        self._msg_id = msg["id"]
        user = getattr(connection, "user", None)
        self._ticket = monitor.begin(
            api_version=version,
            command=str(msg.get("type", "")),
            message=msg,
            user_id=getattr(user, "id", None),
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def send_result(self, msg_id: int, result: Any) -> Any:
        if msg_id == self._msg_id and self._ticket is not None:
            status = "success"
            if isinstance(result, dict):
                raw = str(result.get("status", "")).lower()
                if raw in ("unavailable", "no_data", "no_coverage"):
                    status = "no_data"
                elif raw in ("error", "rejected"):
                    status = "error"
            try:
                self._monitor.finish(self._ticket, result=status, response=result,
                                     providers=_providers_from_response(result))
            except Exception:
                pass  # Monitoring must never alter the Consumer API result.
            self._ticket = None
        return self._connection.send_result(msg_id, result)

    def send_error(self, msg_id: int, code: str, message: str) -> Any:
        if msg_id == self._msg_id and self._ticket is not None:
            status = "timeout" if "timeout" in code else "error"
            try:
                self._monitor.finish(self._ticket, result=status,
                                     error_code=code, response={"message": str(message)[:160]})
            except Exception:
                pass  # Preserve the actual error even if diagnostics fail.
            self._ticket = None
        return self._connection.send_error(msg_id, code, message)


def monitored_connection(hass: Any, connection: Any, msg: dict[str, Any],
                         version: str) -> Any:
    """Return raw connection with zero per-message allocations while disabled."""
    monitor = get_monitor(hass)
    if not monitor.enabled:
        return connection
    return MonitoredConnection(connection, monitor, msg, version)
