"""P7-010: bounded, opt-in asynchronous V2 raster orchestration (isolated).

No Home Assistant imports, no registered websocket endpoint, no provider
secrets, no network implementation and no change to Consumer API V1.
The caller MUST supply trusted, already globally/profile/health-authorized
provider descriptors, never authorization flags from consumer request data.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Awaitable, Callable, Mapping, Sequence

from .raster_mosaic_adapter import make_mosaic_candidate
from .raster_mosaic_contract import validate_raster_mosaic_request
from .raster_mosaic_policy import plan_raster_mosaic, viewport_overlap

MAX_CANDIDATE_CONTACTS = 12
MAX_PARALLEL_CONTACTS = 3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _contact_priority(source: Mapping[str, Any],
                      viewport: Mapping[str, Any]) -> tuple[float, str]:
    """Approximate geographic usefulness without any provider contact."""
    coverage = source.get("machine_coverage")
    try:
        overlap = viewport_overlap(viewport, coverage)
    except (TypeError, ValueError):
        overlap = 0
    return (-overlap, str(source.get("source_id") or ""))


async def resolve_mosaic_snapshot(
    request: Mapping[str, Any],
    *,
    sources: Sequence[Mapping[str, Any]],
    server_now: str | None = None,
    fetch_timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    """Resolve trusted provider descriptors to a non-operational V2 plan.

    Descriptor:
      source_id, eligible (trusted core policy), machine_coverage
      (trusted provider capability or freshly resolved), semantics,
      routing_score, async_fetch(): already V1-public-sanitized raster payload.

    The user never controls source lists, authorization flags, URLs or fetchers.
    No external tile requests are made here. The request max_tile_requests is
    only passed through as a later rendering budget; the active renderer must
    independently enforce it when wired. Fail closed on provider errors.
    """
    query = validate_raster_mosaic_request(request)
    now = server_now if server_now is not None else _utc_now()
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
        raise TypeError("Trusted source inventory must be a sequence")
    if (isinstance(fetch_timeout_seconds, bool)
            or not isinstance(fetch_timeout_seconds, (int, float))
            or not isfinite(fetch_timeout_seconds)
            or not 0 < fetch_timeout_seconds <= 15):
        raise ValueError("Invalid per-provider timeout")
    viewport = {name: query["context"][name]
                for name in ("west", "south", "east", "north")}
    limits = query["limits"]
    # Every simultaneously rendered layer costs at least one tile request.
    # Reject plans already larger than the consumer's complete request budget.
    # Until the active Gewitterradar GridLayer can safely compose more,
    # never return a mosaic with more than four active layers.
    active_layer_budget = min(limits["max_layers"], limits["max_tile_requests"], 4)
    # Provider contacts and composited layers are separate resource budgets.
    # A low layer limit must not silently reduce discovery of geographically
    # suitable sources; the hard request contact and concurrency caps remain.
    contact_budget = MAX_CANDIDATE_CONTACTS
    eligible: list[Mapping[str, Any]] = []
    for source in sources:
        if (not isinstance(source, Mapping) or source.get("eligible") is not True
                or not callable(source.get("async_fetch"))):
            continue
        coverage = source.get("machine_coverage")
        if not isinstance(coverage, Mapping):
            continue
        if _contact_priority(source, viewport)[0] >= 0:
            continue
        eligible.append(source)
    eligible.sort(key=lambda row: _contact_priority(row, viewport))
    limited = eligible[:contact_budget]
    omitted_for_budget = max(0, len(eligible) - len(limited))
    semaphore = asyncio.Semaphore(MAX_PARALLEL_CONTACTS)

    async def _fetch(source: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            async with semaphore:
                payload = await asyncio.wait_for(
                    source["async_fetch"](), timeout=fetch_timeout_seconds)
            if not isinstance(payload, Mapping):
                return None
            return make_mosaic_candidate(
                source_id=source["source_id"],
                eligible=True,
                machine_coverage=source["machine_coverage"],
                payload=payload,
                semantics=source["semantics"],
                data_time=(payload.get("frame_time")
                           or payload.get("data_time")),
                retrieved_at=now,
                routing_score=tuple(source.get("routing_score") or (999, 999, 999)),
            )
        except (Exception):  # noqa: BLE001 - one failing provider must not collapse a mosaic
            return None

    # Gather bounded provider calls. No background jobs survive this call.
    resolved = await asyncio.gather(*(_fetch(row) for row in limited))
    accepted = [row for row in resolved if row is not None]
    temporal = query["time"]
    answer = plan_raster_mosaic(
        accepted,
        viewport=viewport,
        focus=query["context"].get("focus"),
        now=now,
        max_data_age_seconds=temporal["max_data_age_seconds"],
        max_time_delta_seconds=temporal.get("max_time_delta_seconds", 180),
        max_layers=active_layer_budget,
        reference_time=(temporal.get("target_time")
                        if temporal["mode"] == "at_time" else None),
    )
    answer["limitations"].append(
        "Kachelbudget muss durch spaeteren aktiven Renderer erzwungen werden")
    if active_layer_budget < limits["max_layers"]:
        answer["limitations"].append(
            "Quellenzahl durch angefordertes Kachelbudget eingeschraenkt")
    if limits["max_layers"] > 4:
        answer["limitations"].append(
            "Gewitterradar-Rasterdarstellung vorerst auf vier Quellen begrenzt"
        )
    if omitted_for_budget:
        answer["limitations"].append(
            f"{omitted_for_budget} weitere Quellen wegen Kontaktbegrenzung nicht abgefragt")
    if len(accepted) < len(limited):
        answer["limitations"].append(
            f"{len(limited) - len(accepted)} Quellen nicht auswertbar oder nicht erreichbar")
    return answer
