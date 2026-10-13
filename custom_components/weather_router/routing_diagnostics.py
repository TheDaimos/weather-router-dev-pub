"""Admin-only runtime store and WebSocket API for Consumer routing diagnostics."""

from __future__ import annotations

from collections import Counter, deque
from copy import deepcopy
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    API_CONTRACT_VERSION,
    CONSUMER_CONTRACT_VERSION,
    DEV_BUILD_VERSION,
    DEV_LOADER_REV,
    DOMAIN,
)
from .routing_diagnostic_core import (
    ROUTING_DIAGNOSTIC_INDEX_SCHEMA,
    ROUTING_DIAGNOSTIC_LIMIT,
    ROUTING_DIAGNOSTIC_SCHEMA,
    RoutingTraceBuilder,
    diagnostic_value,
    utc_now,
)

_STORE_KEY = f"{DOMAIN}_routing_diagnostics"
_EVENT = f"{DOMAIN}_routing_diagnostic_completed"


def _store(hass: HomeAssistant) -> dict[str, Any]:
    state = hass.data.get(_STORE_KEY)
    if state is None:
        state = {
            "traces": deque(maxlen=ROUTING_DIAGNOSTIC_LIMIT),
            "started_at": utc_now(),
        }
        hass.data[_STORE_KEY] = state
    return state


def _trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    meta = trace.get("meta", {})
    request = trace.get("request", {})
    decision = trace.get("decision", {})
    performance = trace.get("performance", {})
    return {
        "trace_id": meta.get("trace_id"),
        "started_at": meta.get("started_at"),
        "completed_at": meta.get("completed_at"),
        "duration_ms": meta.get("duration_ms"),
        "build_version": meta.get("build_version"),
        "loader_revision": meta.get("loader_revision"),
        "capability": request.get("capability"),
        "family": request.get("family"),
        "phenomena": list(request.get("phenomena") or ()),
        "resource_types": list(request.get("resource_types") or ()),
        "context_type": request.get("context_type"),
        "profile_id": request.get("profile_id"),
        "status": decision.get("status"),
        "code": decision.get("code"),
        "selected_provider": decision.get("selected_provider"),
        "selected_capability": decision.get("selected_capability"),
        "reason_code": decision.get("reason_code"),
        "candidate_count": len(trace.get("candidates", [])),
        "fallback_count": decision.get("fallback_count", 0),
        "providers_contacted": performance.get("providers_contacted"),
    }


def store_routing_trace(hass: HomeAssistant, trace: dict[str, Any]) -> dict[str, Any]:
    """Store one completed bounded trace and notify optional live subscribers."""
    safe = diagnostic_value(trace)
    if not isinstance(safe, dict):
        raise ValueError("routing diagnostic trace must be an object")
    if safe.get("schema") != ROUTING_DIAGNOSTIC_SCHEMA:
        raise ValueError("routing diagnostic trace has unexpected schema")
    state = _store(hass)
    state["traces"].append(safe)
    hass.bus.async_fire(
        _EVENT,
        {
            "schema": ROUTING_DIAGNOSTIC_SCHEMA,
            "summary": _trace_summary(safe),
            "trace": safe,
        },
    )
    return safe


class RoutingTrace(RoutingTraceBuilder):
    """One Consumer resolve trace that stores itself exactly once when finished."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        capability: str,
        contract_version: int | None,
        caller: str = "weather_router/consumer/resolve",
    ) -> None:
        super().__init__(
            capability=capability,
            contract_version=contract_version,
            caller=caller,
            build_version=DEV_BUILD_VERSION,
            loader_revision=DEV_LOADER_REV,
        )
        self._hass = hass
        self._stored: dict[str, Any] | None = None

    def finish(
        self,
        *,
        status: str | None = None,
        code: str | None = None,
    ) -> dict[str, Any]:
        if self._stored is not None:
            return self._stored
        trace = super().finish(status=status, code=code)
        self._stored = store_routing_trace(self._hass, trace)
        return self._stored


def begin_routing_trace(
    hass: HomeAssistant,
    *,
    capability: str,
    contract_version: int | None,
) -> RoutingTrace:
    """Start one in-memory routing trace. No provider/network work is performed."""
    return RoutingTrace(
        hass,
        capability=capability,
        contract_version=contract_version,
    )


def routing_traces(
    hass: HomeAssistant,
    *,
    limit: int = ROUTING_DIAGNOSTIC_LIMIT,
) -> list[dict[str, Any]]:
    """Return newest traces first as independent objects."""
    items = list(_store(hass)["traces"])
    return [deepcopy(item) for item in reversed(items[-max(1, min(limit, ROUTING_DIAGNOSTIC_LIMIT)):])]


def routing_trace_by_id(
    hass: HomeAssistant,
    trace_id: str,
) -> dict[str, Any] | None:
    for trace in reversed(_store(hass)["traces"]):
        if trace.get("meta", {}).get("trace_id") == trace_id:
            return deepcopy(trace)
    return None


def clear_routing_traces(hass: HomeAssistant) -> int:
    traces = _store(hass)["traces"]
    count = len(traces)
    traces.clear()
    return count


def routing_diagnostic_summary(hass: HomeAssistant) -> dict[str, Any]:
    """Return privacy-light ConfigEntry diagnostic metadata, never request coordinates."""
    traces = list(_store(hass)["traces"])
    last_success: dict[str, Any] | None = None
    error_classes: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    for trace in traces:
        decision = trace.get("decision", {})
        status = str(decision.get("status") or "unknown")
        status_counts[status] += 1
        if status == "ready":
            last_success = _trace_summary(trace)
        for error in trace.get("errors", []):
            if not isinstance(error, dict):
                continue
            name = str(error.get("exception_type") or error.get("code") or "unknown")
            error_classes[name] += 1

    if last_success is not None:
        last_success = {
            key: value
            for key, value in last_success.items()
            if key not in {"phenomena"}
        }
    return {
        "schema": ROUTING_DIAGNOSTIC_SCHEMA,
        "ring_limit": ROUTING_DIAGNOSTIC_LIMIT,
        "stored_trace_count": len(traces),
        "status_counts": dict(status_counts),
        "last_success": last_success,
        "error_classes": dict(error_classes.most_common(20)),
        "consumer_contract_version": CONSUMER_CONTRACT_VERSION,
        "diagnostic_api_version": API_CONTRACT_VERSION,
    }


def provider_runtime_summary(
    hass: HomeAssistant,
    provider_id: str,
) -> dict[str, Any]:
    """Derive last selected/failure state for one provider from bounded traces."""
    last_success = None
    last_failure = None
    selected_count = 0
    attempted_count = 0
    for trace in reversed(list(_store(hass)["traces"])):
        for candidate in trace.get("candidates", []):
            if not isinstance(candidate, dict) or candidate.get("provider_id") != provider_id:
                continue
            if candidate.get("attempted"):
                attempted_count += 1
            if candidate.get("result") == "selected":
                selected_count += 1
                if last_success is None:
                    last_success = {
                        "time": trace.get("meta", {}).get("completed_at"),
                        "capability": trace.get("request", {}).get("capability"),
                        "internal_capability": candidate.get("capability_id"),
                        "duration_ms": candidate.get("duration_ms"),
                    }
            elif candidate.get("result") in {"rejected", "failed"} and last_failure is None:
                last_failure = {
                    "time": trace.get("meta", {}).get("completed_at"),
                    "capability": trace.get("request", {}).get("capability"),
                    "internal_capability": candidate.get("capability_id"),
                    "reason": candidate.get("reason"),
                }
    if last_failure is not None and last_success is None:
        health = "degraded"
    elif last_success is not None:
        health = "observed_success"
    else:
        health = "unknown"
    return {
        "health": health,
        "observability": "routing_trace_ring",
        "attempted_count_in_ring": attempted_count,
        "selected_count_in_ring": selected_count,
        "last_success": last_success,
        "last_failure": last_failure,
    }


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "weather_router/routing_diagnostics",
        vol.Optional("limit", default=20): vol.All(int, vol.Range(min=1, max=ROUTING_DIAGNOSTIC_LIMIT)),
        vol.Optional("trace_id"): str,
    }
)
@websocket_api.async_response
async def websocket_routing_diagnostics(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return routing trace summaries or one full trace."""
    trace_id = msg.get("trace_id")
    if trace_id:
        trace = routing_trace_by_id(hass, trace_id)
        if trace is None:
            connection.send_error(msg["id"], "routing_diagnostic_not_found", trace_id)
            return
        connection.send_result(msg["id"], trace)
        return

    traces = routing_traces(hass, limit=msg["limit"])
    connection.send_result(
        msg["id"],
        {
            "schema": ROUTING_DIAGNOSTIC_INDEX_SCHEMA,
            "generated_at": utc_now(),
            "trace_schema": ROUTING_DIAGNOSTIC_SCHEMA,
            "ring_limit": ROUTING_DIAGNOSTIC_LIMIT,
            "traces": [_trace_summary(item) for item in traces],
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "weather_router/routing_diagnostics_clear"}
)
@websocket_api.async_response
async def websocket_routing_diagnostics_clear(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Clear only the ephemeral routing diagnostic ring."""
    cleared = clear_routing_traces(hass)
    connection.send_result(
        msg["id"],
        {
            "cleared": cleared,
            "remaining": 0,
            "schema": ROUTING_DIAGNOSTIC_INDEX_SCHEMA,
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): "weather_router/routing_diagnostics_subscribe"}
)
@websocket_api.async_response
async def websocket_routing_diagnostics_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to completed routing traces without polling or provider I/O."""

    @callback
    def _forward(event: Event) -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"],
                diagnostic_value(event.data),
            )
        )

    connection.subscriptions[msg["id"]] = hass.bus.async_listen(_EVENT, _forward)
    connection.send_result(msg["id"])


def async_register(hass: HomeAssistant) -> None:
    """Register admin-only routing diagnostic commands."""
    websocket_api.async_register_command(hass, websocket_routing_diagnostics)
    websocket_api.async_register_command(hass, websocket_routing_diagnostics_clear)
    websocket_api.async_register_command(hass, websocket_routing_diagnostics_subscribe)
