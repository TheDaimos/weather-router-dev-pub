"""P7-010: bounded UTC event-window policy for existing Consumer V1 feeds.

This is NOT a precipitation/mosaic command or a new event WebSocket. The
provider and permission/routing decisions remain in consumer_api.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import json
from typing import Any, Mapping

from .time_normalization import iso_instant, utc_iso

UTC = timezone.utc
_MAX_RESULTS = 200
_MAX_PAGES = 5
_MAX_SCANNED_EVENTS = 1000
_CLOSED = frozenset({"ended", "resolved", "expired", "cancelled", "canceled",
                     "cleared", "withdrawn", "inactive", "closed"})
_ACTIVE = frozenset({"active", "ongoing", "in_progress", "erupting",
                     "warning", "watch", "in_effect"})
_CLASSES = {
    "official_warning": {"days": 31, "feed_seconds": 3600,
                         "ongoing_seconds": 21600},
    "long_running_event": {"days": 366, "feed_seconds": 172800,
                           "ongoing_seconds": 604800},
    "point_event": {"days": 366, "feed_seconds": 86400,
                    "ongoing_seconds": 0},
    "historical_sighting": {"days": 366, "feed_seconds": 86400,
                            "ongoing_seconds": 0},
}


@lru_cache(maxsize=1)
def _declared_policies() -> dict[str, Any]:
    path = Path(__file__).with_name("consumer_event_time_policies.v1.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "weather_router.consumer.event_time_policies.v1":
        raise ValueError("invalid_event_policy_catalog")
    return doc["public_capabilities"]


def time_class(public_id: str, resource_type: str) -> str | None:
    """Only the trusted public intent table may enable event-window filtering."""
    row = _declared_policies().get(public_id)
    if not isinstance(row, dict) or row.get("resource_type") != resource_type:
        return None
    cls = row.get("time_class")
    return cls if cls in _CLASSES else None


def _instant(value: Any) -> datetime | None:
    normalized = iso_instant(value)
    if normalized is None:
        return None
    return datetime.fromisoformat(normalized.replace("Z", "+00:00"))


def validate_event_time(raw: Any, *, public_id: str, resource_types: set[str],
                        now: datetime | None = None) -> dict[str, Any]:
    """Validate optional event mode against server-authorized capability resources."""
    if not isinstance(raw, dict) or raw.get("mode") != "events_intersecting_window":
        raise ValueError("invalid_event_time_mode")
    if set(raw) - {"mode", "window", "include_ongoing",
                   "max_feed_update_age_seconds", "page", "page_size"}:
        raise ValueError("unknown_event_time_fields")
    if resource_types != {"hazard_feed"} and resource_types != {"event_feed"}:
        raise ValueError("event_window_requires_single_feed_resource")
    cls = time_class(public_id, next(iter(resource_types)))
    if cls is None:
        raise ValueError("unsupported_event_time_capability")
    limits = _CLASSES[cls]
    window = raw.get("window")
    if not isinstance(window, dict) or set(window) != {"start", "end"}:
        raise ValueError("invalid_event_window")
    start, end = _instant(window["start"]), _instant(window["end"])
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if start is None or end is None or start > end:
        raise ValueError("invalid_event_window")
    if end - start > timedelta(days=limits["days"]):
        raise ValueError("event_window_too_large")
    if end > current + timedelta(minutes=5):
        raise ValueError("future_event_window")
    if type(raw.get("include_ongoing", False)) is not bool:
        raise ValueError("invalid_include_ongoing")
    page = raw.get("page", 1)
    page_size = raw.get("page_size", _MAX_RESULTS)
    if type(page) is not int or not 1 <= page <= _MAX_PAGES:
        raise ValueError("event_page_out_of_bounds")
    if type(page_size) is not int or not 1 <= page_size <= _MAX_RESULTS:
        raise ValueError("event_page_size_out_of_bounds")
    feed_budget = raw.get("max_feed_update_age_seconds", limits["feed_seconds"])
    if type(feed_budget) is not int or not 60 <= feed_budget <= limits["feed_seconds"] * 4:
        raise ValueError("invalid_feed_update_age")
    return {
        "mode": "events_intersecting_window",
        "window": {"start": utc_iso(start), "end": utc_iso(end)},
        "include_ongoing": raw.get("include_ongoing", False),
        "max_feed_update_age_seconds": feed_budget,
        "class": cls,
        "max_window_days": limits["days"],
        "max_results": _MAX_RESULTS,
        "page": page,
        "page_size": page_size,
        "max_pages": _MAX_PAGES,
        "max_ongoing_update_age_seconds": limits["ongoing_seconds"],
    }


def filter_event_payload(payload: Mapping[str, Any], *, time: Mapping[str, Any],
                         provider_result: Mapping[str, Any] | None = None,
                         now: datetime | None = None) -> dict[str, Any]:
    """Bound feed event results and keep unknown/old states explicit.

    Only an explicit active status with a *real provider update timestamp*
    can establish unknown-end ongoing activity. A fetch timestamp is never
    used to manufacture event duration or freshness.
    """
    current = (now or datetime.now(UTC)).astimezone(UTC)
    start = _instant(time["window"]["start"])
    end = _instant(time["window"]["end"])
    if start is None or end is None:
        raise ValueError("invalid_validated_window")
    source = provider_result if isinstance(provider_result, Mapping) else {}
    updated = next((v for field in ("last_updated_at", "published_at", "feed_updated_at")
                    if (v := _instant(source.get(field))) is not None), None)
    source_age = (current - updated).total_seconds() if updated else None
    feed_status = ("unknown" if source_age is None else
                   "future" if source_age < -300 else
                   "stale" if source_age > time["max_feed_update_age_seconds"] else
                   "fresh")
    page = time.get("page", 1)
    page_size = time.get("page_size", _MAX_RESULTS)
    if type(page) is not int or not 1 <= page <= _MAX_PAGES:
        raise ValueError("invalid_validated_page")
    if type(page_size) is not int or not 1 <= page_size <= _MAX_RESULTS:
        raise ValueError("invalid_validated_page_size")
    page_end = page * page_size
    page_start = page_end - page_size
    accepted: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    input_events = payload.get("events", [])
    if not isinstance(input_events, list):
        input_events = []

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for event in input_events[:_MAX_SCANNED_EVENTS]:
        if not isinstance(event, dict):
            reject("invalid_event")
            continue
        state = str(event.get("lifecycle_status") or event.get("status") or "").strip().lower()
        closed = state in _CLOSED
        kind = time["class"]
        # Point observations are anchored to actual occurrence, not to the
        # later publication/effective time of a bulletin about that event.
        event_time_fields = (
            ("observed_at", "occurred_at", "started_at", "valid_from",
             "effective", "onset", "sent")
            if kind in {"point_event", "historical_sighting"}
            else ("valid_from", "effective", "onset", "started_at",
                  "occurred_at", "observed_at", "sent")
        )
        begins = next((v for field in event_time_fields
                       if (v := _instant(event.get(field))) is not None), None)
        ends = next((v for field in ("resolved_at", "ended_at", "ends",
                                      "expires", "valid_until")
                     if (v := _instant(event.get(field))) is not None), None)
        if begins is None:
            reject("missing_event_time")
            continue
        if begins > end:
            reject("after_window")
            continue
        if kind in {"point_event", "historical_sighting"} and begins > current:
            reject("future_observation")
            continue
        if ends is not None and ends < start:
            reject("ended_before_window")
            continue
        if ends is not None and ends < begins:
            reject("invalid_event_interval")
            continue
        # A point event/observation is historical even if the provider uses
        # a vague active label. It does not establish an ongoing location.
        volcano_meta = event.get("volcano_semantics")
        weekly_report = (isinstance(volcano_meta, Mapping)
                         and volcano_meta.get("semantic_class")
                             == "weekly_volcanic_activity_report_event")
        point = kind in {"point_event", "historical_sighting"} or weekly_report
        ongoing = False
        scheduled = not point and begins > current
        if point:
            if begins < start:
                reject("before_window")
                continue
        elif ends is None:
            if closed:
                reject("closed_without_verified_end")
                continue
            # A newly refreshed *feed* is not evidence that this particular
            # open-ended event remains active. Require its own source timestamp.
            recent_update = next((v for field in ("last_updated_at", "published_at")
                                  if (v := _instant(event.get(field))) is not None),
                                 None)
            age = (current - recent_update).total_seconds() if recent_update else None
            if not (time["include_ongoing"] and state in _ACTIVE
                    and age is not None
                    and 0 <= age <= time["max_ongoing_update_age_seconds"]):
                reject("unverified_ongoing")
                continue
            ongoing = True
        elif closed and ends > current:
            reject("closed_status_conflict")
            continue
        elif ends > current:
            ongoing = not closed and not scheduled
        elif ends <= current and ends < start:
            reject("ended_before_window")
            continue
        if ongoing and not time["include_ongoing"]:
            reject("ongoing_disabled")
            continue
        entry = dict(event)
        entry["event_time_class"] = kind
        entry["temporal_status"] = (
            "historical_observation" if kind == "historical_sighting"
            else "historical_event" if point
            else "ongoing" if ongoing else "scheduled" if scheduled
            else "ended" if ends and ends <= current else "time_bounded")
        accepted.append(entry)
        # One look-ahead confirms the next page without fetching more feeds.
        if len(accepted) > page_end:
            break

    page_events = accepted[page_start:page_end]
    more = len(accepted) > page_end or len(input_events) > _MAX_SCANNED_EVENTS
    filtered = dict(payload)
    filtered["events"] = page_events
    filtered["event_count"] = len(page_events)
    filtered["event_time_policy"] = {
        "class": time["class"],
        "window": dict(time["window"]),
        "include_ongoing": time["include_ongoing"],
        "max_results": _MAX_RESULTS,
        "page": page,
        "page_size": page_size,
        "max_pages": _MAX_PAGES,
        "has_more": more,
        "feed_status": feed_status,
        "feed_updated_at": utc_iso(updated) if updated else None,
        "feed_age_seconds": round(source_age, 1) if source_age is not None else None,
        "max_feed_update_age_seconds": time["max_feed_update_age_seconds"],
        "rejected_counts": rejected,
        "truncated": more,
        "rejection_counts_scope": "scanned_prefix",
    }
    return filtered
