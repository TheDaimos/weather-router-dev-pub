"""P7-010: deterministic, provider-neutral spatial/temporal raster mosaic planner.

An isolated *pure* component, NOT connected to Consumer API V1 or to a live
provider. Callers must enforce global router/domain/provider permissions,
deny-only profiles, health, licences and actual resource eligibility before
setting eligible=True. Verified machine coverage is mandatory.

This planner returns clipping envelopes and explicit source semantics, never
alters pixel values, guesses data gaps, or blends unlike observations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite, log, pi, tan
from typing import Any, Mapping

MERCATOR_LAT = 85.05112878


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _bbox(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    values: dict[str, float] = {}
    for field, low, high in (("west", -180, 180), ("east", -180, 180),
                             ("south", -90, 90), ("north", -90, 90)):
        n = value.get(field)
        if isinstance(n, bool) or not isinstance(n, (int, float)):
            return None
        if not isfinite(n) or not low <= n <= high:
            return None
        values[field] = float(n)
    if values["north"] <= values["south"] or values["west"] == values["east"]:
        return None
    return values


def _segments(bbox: Mapping[str, float]) -> tuple[tuple[float, float], ...]:
    west, east = bbox["west"], bbox["east"]
    return ((west, east),) if west < east else ((west, 180.0), (-180.0, east))


def _mercator(latitude: float) -> float:
    phi = max(-MERCATOR_LAT, min(MERCATOR_LAT, latitude))
    return log(tan(pi / 4 + phi * pi / 360))


def viewport_overlap(viewport: Mapping[str, float], coverage: Mapping[str, Any]) -> float:
    """Fraction of Mercator screen area covered by a verified bbox envelope.

    This is not proof that all pixels in a provider bbox contain valid data.
    Both bboxes may cross the antimeridian. Full-world bounds are [-180,180].
    """
    view = _bbox(viewport)
    if view is None:
        raise ValueError("invalid viewport")
    if not isinstance(coverage, Mapping):
        return 0.0
    if coverage.get("scope") == "global":
        return 1.0
    if coverage.get("scope") != "bbox":
        return 0.0
    region = _bbox(coverage.get("bbox"))
    if region is None:
        return 0.0
    top = min(view["north"], region["north"], MERCATOR_LAT)
    bottom = max(view["south"], region["south"], -MERCATOR_LAT)
    total_top = min(view["north"], MERCATOR_LAT)
    total_bottom = max(view["south"], -MERCATOR_LAT)
    if top <= bottom or total_top <= total_bottom:
        return 0.0
    overlap_width = sum(max(0.0, min(ve, re) - max(vw, rw))
                        for vw, ve in _segments(view)
                        for rw, re in _segments(region))
    view_width = sum(e - w for w, e in _segments(view))
    return max(0.0, min(1.0, (overlap_width / view_width)
                        * ((_mercator(top) - _mercator(bottom))
                           / (_mercator(total_top) - _mercator(total_bottom)))))


def _point_inside(point: Mapping[str, Any] | None, coverage: Mapping[str, Any]) -> bool:
    if not isinstance(point, Mapping) or not isinstance(coverage, Mapping):
        return False
    lat, lon = point.get("latitude"), point.get("longitude")
    if any(isinstance(n, bool) or not isinstance(n, (int, float))
           or not isfinite(n) for n in (lat, lon)):
        return False
    if coverage.get("scope") == "global":
        return True
    box = _bbox(coverage.get("bbox"))
    if box is None or not box["south"] <= lat <= box["north"]:
        return False
    return any(w <= lon <= e for w, e in _segments(box))


def _semantics(candidate: Mapping[str, Any]) -> dict[str, str] | None:
    info = candidate.get("semantics")
    keys = ("quantity", "unit", "measurement_method", "observation_kind")
    if not isinstance(info, Mapping) or any(
        not isinstance(info.get(k), str) or not info[k].strip() for k in keys
    ):
        return None
    return {k: info[k] for k in keys}


def _usable_frames(candidate: Mapping[str, Any], now_dt: datetime,
                   max_age_seconds: int) -> list[dict[str, Any]]:
    """Fresh, time-labelled tile frames only; never infer time from retrieval."""
    raw = candidate.get("frames")
    if raw is None:
        raw = [{"data_time": candidate.get("data_time"),
                "tile_url": candidate.get("tile_url")}]
    if not isinstance(raw, list) or len(raw) > 24:
        return []
    accepted: dict[datetime, dict[str, Any]] = {}
    for frame in raw:
        if not isinstance(frame, Mapping):
            continue
        timestamp = _time(frame.get("data_time"))
        tile_url = frame.get("tile_url")
        if (timestamp is None or not isinstance(tile_url, str)
                or not tile_url.startswith("https://")):
            continue
        age = (now_dt - timestamp).total_seconds()
        if 0 <= age <= max_age_seconds:
            accepted[timestamp] = {"time": timestamp, "tile_url": tile_url}
    return sorted(accepted.values(), key=lambda f: f["time"], reverse=True)


def _align_frame(item: dict[str, Any], anchor: datetime,
                 tolerance_seconds: int) -> None:
    """Choose nearest fresh frame if coherent; otherwise keep newest."""
    frames = item["frames"]
    coherent = [f for f in frames
                if abs((f["time"] - anchor).total_seconds()) <= tolerance_seconds]
    frame = (min(coherent, key=lambda f:
                 (abs((f["time"] - anchor).total_seconds()),
                  -f["time"].timestamp()))
             if coherent else frames[0])
    item["time"] = frame["time"]
    item["tile_url"] = frame["tile_url"]


def plan_raster_mosaic(
    candidates: list[Mapping[str, Any]], *,
    viewport: Mapping[str, float],
    now: str,
    max_data_age_seconds: int,
    max_time_delta_seconds: int,
    max_layers: int = 4,
    focus: Mapping[str, Any] | None = None,
    reference_time: str | None = None,
) -> dict[str, Any]:
    """Produce a budgeted *non-operational* V2 mosaic plan from prechecked data.

    Candidate fields: source_id, eligible, verified_coverage, coverage
    {scope:bbox,bbox:{...}} or {scope:global}, resource_type, data_time,
    semantics, tile_url, attribution, legend, optional routing_score.
    No provider-specific rules or live retrievals are performed.
    """
    box = _bbox(viewport)
    now_dt = _time(now)
    target_dt = _time(reference_time) if reference_time is not None else None
    if box is None or now_dt is None or (reference_time is not None and target_dt is None):
        raise ValueError("invalid viewport or time")
    for value, low, high in ((max_data_age_seconds, 1, 86400),
                             (max_time_delta_seconds, 0, 86400),
                             (max_layers, 1, 12)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError("invalid resource or freshness limit")
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")
    allowed: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            rejected.append({"source_id": "", "reason": "invalid_candidate"})
            continue
        source_id = candidate.get("source_id")
        source_id = source_id if isinstance(source_id, str) else ""
        reason = ""
        if not source_id or source_id in seen:
            reason = "missing_or_duplicate_source"
        else:
            seen.add(source_id)
        coverage = candidate.get("coverage")
        sem = _semantics(candidate)
        if not reason and (candidate.get("eligible") is not True
                           or candidate.get("verified_coverage") is not True):
            reason = "not_eligible_or_unverified_coverage"
        if not reason and (candidate.get("resource_type") != "raster_tile"
                           or sem is None or not isinstance(candidate.get("legend"), Mapping)
                           or not isinstance(candidate.get("attribution"), str)
                           or not candidate["attribution"].strip()):
            reason = "missing_or_incompatible_raster_metadata"
        if not reason and not isinstance(coverage, Mapping):
            reason = "invalid_coverage"
        fraction = viewport_overlap(box, coverage) if not reason else 0.0
        if not reason and fraction <= 0.0:
            reason = "outside_coverage"
        frames = _usable_frames(candidate, now_dt, max_data_age_seconds)
        if not reason and not frames:
            reason = "no_fresh_verified_frame"
        timestamp = frames[0]["time"] if frames else None
        if reason:
            rejected.append({"source_id": source_id, "reason": reason})
            continue
        raw_score = candidate.get("routing_score")
        score = (tuple(raw_score) if isinstance(raw_score, (tuple, list))
                 and len(raw_score) == 3
                 and all(type(n) is int for n in raw_score)
                 else (999, 999, 999))
        allowed.append({
            "candidate": candidate, "semantics": sem, "time": timestamp,
            "tile_url": frames[0]["tile_url"], "frames": frames,
            "fraction": fraction, "focus": _point_inside(focus, coverage),
            "score": score,
        })
    # Pick a demonstrably broad foundation before any regional refinement.
    # Regional candidates are independent, geographically clipped overlays:
    # prefer actual viewer focus, time-coherence with the foundation, then
    # spatial relevance and existing provider-neutral semantic scoring.
    allowed.sort(key=lambda a: (-a["fraction"], a["score"],
                                -a["time"].timestamp(),
                                str(a["candidate"]["source_id"])))
    if allowed:
        foundation = allowed[0]
        anchor = target_dt or foundation["time"]
        _align_frame(foundation, anchor, max_time_delta_seconds)
        others = allowed[1:]
        for other in others:
            _align_frame(other, anchor, max_time_delta_seconds)
        others.sort(
            key=lambda a: (
                not a["focus"],
                abs((a["time"] - anchor).total_seconds()) > max_time_delta_seconds,
                -a["fraction"],
                abs((a["time"] - anchor).total_seconds()),
                a["score"],
                str(a["candidate"]["source_id"]),
            )
        )
        ordered = [foundation, *others]
    else:
        ordered = []
    selected = ordered[:max_layers]
    for item in ordered[max_layers:]:
        rejected.append({"source_id": item["candidate"]["source_id"],
                         "reason": "layer_budget"})
    reference = target_dt if target_dt is not None else (
        selected[0]["time"] if selected else None)
    layers: list[dict[str, Any]] = []
    for index, item in enumerate(selected):
        candidate = item["candidate"]
        timestamp = item["time"]
        delta = abs((timestamp - reference).total_seconds()) if reference else None
        coverage = candidate["coverage"]
        area = ({"west": -180.0, "east": 180.0, "south": -90.0, "north": 90.0}
                if coverage["scope"] == "global" else _bbox(coverage["bbox"]))
        layers.append({
            "source_id": candidate["source_id"],
            "resource_type": "raster_tile",
            "coverage": area,
            "coverage_verified": True,  # verified envelope, NOT a complete pixel mask
            "coverage_scope": coverage["scope"],
            "tile_url": item["tile_url"],
            "semantics": item["semantics"],
            "times": {
                "valid_at": _iso(timestamp),
                # A layer validity frame is not proof of an observation time.
                "observed_at": None,
                "retrieved_at": (candidate["retrieved_at"]
                                 if isinstance(candidate.get("retrieved_at"), str)
                                 and _time(candidate["retrieved_at"]) is not None
                                 else _iso(now_dt)),
                "reference_delta_seconds": delta,
            },
            "attribution": candidate["attribution"],
            "legend": dict(candidate["legend"]),
            "quality_note": ("zeitlich_abweichend" if delta is not None
                             and delta > max_time_delta_seconds
                             else "zeitlich_passend"),
        })
    full_world_verified = bool(selected and
                               selected[0]["candidate"]["coverage"]["scope"] == "global")
    # Even with global coverage, valid raster pixels are not independently
    # established, so only claim partial until resource masks are validated.
    limitations = ["Rasterpixel und Datenluecken nicht vollstaendig verifiziert"]
    if not full_world_verified:
        limitations.append("Keine belastbare durchgehende Grundversorgung belegt")
    if any(layer["quality_note"] == "zeitlich_abweichend" for layer in layers):
        limitations.append("Quellenzeitstaende weichen vom Bezugszeitpunkt ab")
    if any(item["reason"] == "layer_budget" for item in rejected):
        limitations.append("Weitere Quellen wegen Ressourcenbegrenzung ausgelassen")
    return {
        "contract_version": 2,
        "capability": "weather.precipitation.layer",
        "status": "partial" if layers else "unavailable",
        "viewport": box,
        "reference_time": _iso(reference) if reference else None,
        "layers": layers,
        "limitations": limitations,
    }
