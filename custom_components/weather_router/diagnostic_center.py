"""D2 bounded on-demand diagnostics using existing HA and provider infrastructure.

No periodic probes, no secrets, no precise locations, no native import probes,
no private extension implementation knowledge, no system mutation.
"""
from __future__ import annotations

from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
import platform
import sys
import sysconfig
import time
from typing import Any

_MAX_EVENTS = 180
_KEY = "weather_router_d2_diagnostics"
_ACTIVE_CORRELATION: ContextVar[str | None] = ContextVar("weather_router_d2_request", default=None)


def active_request_correlation() -> str | None:
    """Return the already validated request ID in this async call context."""
    return _ACTIVE_CORRELATION.get()


def bind_request_correlation(correlation_id: str):
    """Bind an internal request ID only for the current async context."""
    from .d2_trace import _SAFE_ID
    if not isinstance(correlation_id, str) or not _SAFE_ID.fullmatch(correlation_id):
        return None
    return _ACTIVE_CORRELATION.set(correlation_id)


def reset_request_correlation(token):
    if token is not None:
        _ACTIVE_CORRELATION.reset(token)




def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_value(value: Any, *, depth: int = 0) -> Any:
    """Strictly allowlisted provider-neutral summary; never export raw payloads."""
    if depth > 3:
        return None
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        from math import isfinite
        return value if isfinite(value) and abs(value) < 1e15 else None
    if isinstance(value, str):
        # No arbitrary extension-generated strings (URLs, paths or identifiers).
        return value[:120] if value.replace("_", "").replace("-", "").isalnum() else None
    if isinstance(value, dict):
        allowed = {
            "started", "ready", "initialized", "source_available", "available",
            "direct_receiver_count", "receiver_count", "buffered_event_count",
            "event_count", "buffer_capacity", "window_seconds", "read_only",
            "second_mqtt_connection", "http_status", "duration_ms",
            "tile_denial_code", "tile_denial_phase",
            "event_loop_yield_ms", "executor_turnaround_ms", "timeout", "expected_absence", "response_bytes", "declared_response_bytes", "candidate_count",
            "listing_pages", "listing_response_bytes", "listing_complete",
            "listing_retry_count", "listing_objects_seen", "listing_truncated",
            "runtime_importable", "scientific_raster_approved",
        }
        return {key: _safe_value(item, depth=depth + 1)
                for key, item in value.items() if key in allowed}
    return None


def _state(hass) -> dict:
    state = hass.data.setdefault(_KEY, {})
    if not isinstance(state.get("events"), deque):
        state["events"] = deque(maxlen=_MAX_EVENTS)
    return state


def record(hass, *, category: str, outcome: str, details: dict | None = None, correlation_id: str | None = None) -> None:
    """Limited process-local timeline without private payload retention."""
    if category not in {"runtime", "provider", "routing", "consumer", "raster", "extension"}:
        return
    if outcome not in {"started", "success", "failed", "unavailable", "recovered", "unloaded"}:
        return
    state = _state(hass)
    from .d2_trace import TraceStore
    trace = state.get("trace")
    if trace is None:
        trace = TraceStore()
        state["trace"] = trace
    state["events"].append({
        "utc": _utc_now(), "category": category, "outcome": outcome,
        "details": _safe_value(details or {}),
    })
    request_id = _ACTIVE_CORRELATION.get()
    trace.emit(category, {"started":"start","success":"success","failed":"failure","unavailable":"unavailable","recovered":"recovered","unloaded":"unloaded"}[outcome],
               correlation_id=request_id or correlation_id,
               source_id=correlation_id if category == "provider" else None,
               metrics=details)
    # A recovery is observed only after a real previous failure for the
    # same validated provider. Unrelated providers cannot contaminate status.
    if (category == "provider" and isinstance(correlation_id, str)
            and not (details or {}).get("expected_absence", False)):
        from .d2_trace import _SAFE_ID
        if _SAFE_ID.fullmatch(correlation_id):
            previous = state.setdefault("last_provider_status", {})
            was_failed = previous.get(correlation_id) in {"failed", "unavailable"}
            if outcome in {"success", "failed", "unavailable"}:
                if correlation_id not in previous and len(previous) >= 128:
                    previous.pop(next(iter(previous)))
                previous[correlation_id] = outcome
            if was_failed and outcome == "success":
                trace.emit("provider", "recovered", correlation_id=request_id or correlation_id,
                           source_id=correlation_id)



def runtime_snapshot() -> dict:
    """Collect bounded current-process metrics in HA-Core executor, never poll."""
    state = {
        "python": ".".join(map(str, sys.version_info[:3])),
        "python_abi": sysconfig.get_config_var("SOABI") or "unknown",
        "architecture": platform.machine(),
        "system": platform.system(),
        "process_cpu_seconds": round(time.process_time(), 3),
        "snapshot_utc": _utc_now(),
    }
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB; Darwin reports bytes.
        state["process_peak_rss_bytes"] = int(peak * (1024 if sys.platform.startswith("linux") else 1))
    except (ImportError, OSError, ValueError):
        state["process_peak_rss_bytes"] = None
    return state


def snapshot(hass, *, runtime: dict, provider_summaries: list[dict] | None = None) -> dict:
    from .const import DEV_BUILD_VERSION, DEV_LOADER_REV
    state = _state(hass)
    summaries = []
    for item in (provider_summaries or [])[:128]:
        if not isinstance(item, dict):
            continue
        summaries.append({
            "provider_id": str(item.get("id") or "")[:64] if str(item.get("id") or "").replace("_", "").isalnum() else "",
            "status": str(item.get("status") or "unknown")[:40] if str(item.get("status") or "").replace("_", "").isalnum() else "unknown",
            "diagnostic": _safe_value(item.get("diagnostic") or {}),
        })
    return {
        "schema": "weather_router.diagnostic_center.v1",
        "generated_at": _utc_now(),
        "version": DEV_BUILD_VERSION,
        "loader": DEV_LOADER_REV,
        "runtime": runtime,
        "providers": summaries,
        "events": list(state["events"])[-120:],
        "trace": state.get("trace").snapshot() if state.get("trace") is not None else [],
        "provider_last_state": {key: value for key, value in list(state.get("last_provider_status", {}).items())[-128:]},
        "limits": {"providers": 128, "events": 120, "stored_events": _MAX_EVENTS},
        "not_executed": [
            "external_endpoints_not_polled",
            "native_packages_not_imported",
            "private_extension_payloads_not_collected",
            "scientific_raster_approval_not_performed",
        ],
        "scientific_raster_approved": False,
    }


def provider_diagnostic_summary(provider_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Generic extension/provider diagnostic details without private identifiers."""
    state = result.get("data") if isinstance(result.get("data"), dict) else result
    if not isinstance(state, dict):
        state = {}
    safe = _safe_value(state)
    return {"id": provider_id, "status": "success" if result.get("ok") is True
            else "failed" if result.get("ok") is False else "unknown",
            "diagnostic": safe}


def summarize_stations(probe: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose bounded diagnostic stages; no raw network addresses or original data."""
    if not isinstance(probe, dict):
        return []
    stages = []
    for name, fields in (
        ("http_listing", ("listing_http_status", "listing_response_bytes", "listing_retry_count")),
        ("xml_pagination", ("listing_pages", "listing_truncated", "listing_objects_seen", "listing_complete")),
        ("diagnostic_delivery", ("runtime_importable", "scientific_raster_approved")),
    ):
        values = {key: probe[key] for key in fields if key in probe}
        if values:
            stages.append({"stage": name, "observed_at_utc": _utc_now(),
                           "status": "failed" if probe.get("ok") is False else "observed",
                           "values": _safe_value(values)})
    # Additional OPERA steps describe only evidence actually provided by its
    # explicit provider probe; a listing result is never proof of a PNG.
    if "listing_http_status" in probe:
        stages.append({"stage": "xml_parse", "observed_at_utc": _utc_now(),
                       "status": "failed" if probe.get("error") == "invalid_listing_xml"
                       else "observed" if probe.get("listing_truncated") is not None
                       else "unverified"})
    if "rate_matches" in probe:
        stages.append({"stage": "rate_candidate_selection", "observed_at_utc": _utc_now(),
                       "status": "observed",
                       "values": _safe_value({"candidate_count": probe["rate_matches"]})})
    dl = probe.get("download")
    if isinstance(dl, dict):
        stages.append({"stage": "original_data_verification",
                       "observed_at_utc": _utc_now(),
                       "status": "observed" if dl.get("sha256") and dl.get("bytes") else "unverified",
                       "values": _safe_value({"response_bytes": dl.get("bytes")})})
        if dl.get("status") == "dev_diagnostic_unverified":
            stages.append({"stage": "diagnostic_frame_registration",
                           "observed_at_utc": _utc_now(), "status": "observed"})
    elif probe.get("error"):
        stages.append({"stage": "original_data_verification",
                       "observed_at_utc": _utc_now(), "status": "not_executed"})
    if any(key in probe for key in ("listing_http_status", "listing_pages", "rate_matches", "download")):
        stages.append({"stage": "scientific_raster_admission",
                       "observed_at_utc": _utc_now(), "status": "blocked"})
    return stages


def record_http_exchange(hass, provider_id: str, *, started_monotonic: float,
                         http_status: int | None = None,
                         response_bytes: int | None = None,
                         declared_response_bytes: int | None = None,
                         attempts: int = 1, failed: bool = False,
                         absence_codes: tuple[int, ...] = (404, 410),
                         timeout: bool = False) -> None:
    """Provider-neutral observed HTTP exchange. No URL, body or credentials."""
    from math import isfinite
    duration = (time.monotonic() - started_monotonic) * 1000
    details = {
        "duration_ms": round(max(0.0, duration), 2) if isfinite(duration) else None,
        "timeout": timeout if type(timeout) is bool else None,
        "expected_absence": bool(http_status in absence_codes) if type(http_status) is int else False,
        "http_status": http_status if type(http_status) is int and 100 <= http_status <= 599 else None,
        "response_bytes": response_bytes if type(response_bytes) is int and 0 <= response_bytes <= 100_000_000 else None,
        "declared_response_bytes": declared_response_bytes if type(declared_response_bytes) is int and 0 <= declared_response_bytes <= 100_000_000 else None,
        "listing_retry_count": max(0, min(attempts - 1, 100)) if type(attempts) is int else None,
    }
    try:
        status = details["http_status"]
        # Explicit coverage absence is not a service outage and must never
        # create an artificial recovered event on the next geographic query.
        outcome = ("unavailable" if status in absence_codes else
                   "failed" if failed or (status is not None and status >= 400)
                   else "success")
        record(hass, category="provider", correlation_id=provider_id,
               outcome=outcome, details=details)
    except Exception:
        # Telemetry must never break the provider's actual network result.
        return


class _ObservedHttpRequest:
    """Transparent aiohttp request-context adapter; never reads response bodies."""

    def __init__(self, hass, provider_id: str, request, absence_codes=(404, 410)):
        self._hass = hass
        self._provider_id = provider_id
        self._absence_codes = absence_codes
        self._request = request
        self._started = None
        self._response = None
        self._reported = False
        self._timed_out = False

    def _finish(self, *, failed=False):
        if self._reported:
            return
        self._reported = True
        response = self._response
        record_http_exchange(
            self._hass, self._provider_id,
            started_monotonic=self._started if self._started is not None else time.monotonic(),
            http_status=getattr(response, "status", None),
            declared_response_bytes=getattr(response, "content_length", None),
            failed=failed, absence_codes=self._absence_codes,
            timeout=self._timed_out,
        )

    async def __aenter__(self):
        self._started = time.monotonic()
        try:
            self._response = await self._request.__aenter__()
            return self._response
        except BaseException as error:
            self._timed_out = isinstance(error, TimeoutError)
            self._finish(failed=True)
            raise

    async def __aexit__(self, exc_type, exc, tb):
        self._timed_out = isinstance(exc, TimeoutError)
        failed = exc_type is not None
        try:
            return await self._request.__aexit__(exc_type, exc, tb)
        except BaseException as error:
            self._timed_out = self._timed_out or isinstance(error, TimeoutError)
            failed = True
            raise
        finally:
            self._finish(failed=failed)

    def __await__(self):
        async def _await_request():
            self._started = time.monotonic()
            try:
                self._response = await self._request
                self._finish()
                return self._response
            except BaseException as error:
                self._timed_out = isinstance(error, TimeoutError)
                self._finish(failed=True)
                raise
        return _await_request().__await__()


class _ObservedHttpSession:
    """Pass-through for HA's shared session, intercepting requests only."""

    def __init__(self, hass, provider_id: str, session, absence_codes=(404, 410)):
        self._hass = hass
        self._provider_id = provider_id
        self._absence_codes = absence_codes
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def request(self, method, url, **kwargs):
        return _ObservedHttpRequest(
            self._hass, self._provider_id,
            self._session.request(method, url, **kwargs),
            self._absence_codes,
        )

    def get(self, url, **kwargs):
        return _ObservedHttpRequest(self._hass, self._provider_id,
                                    self._session.get(url, **kwargs), self._absence_codes)

    def post(self, url, **kwargs):
        return _ObservedHttpRequest(self._hass, self._provider_id,
                                    self._session.post(url, **kwargs), self._absence_codes)


def observed_clientsession(hass, provider_id: str, session, *, absence_codes=(404, 410)):
    """Reuse the real HA client session with bounded, URL-free D2 observability."""
    return _ObservedHttpSession(hass, provider_id, session, absence_codes)
