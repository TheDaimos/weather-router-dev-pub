"""P7-010 V1-normalized raster to isolated V2 mosaic candidate adapter.

Pure and not activated in the Consumer API. The caller must have enforced the
global router/domain/provider flags, deny-only profile, provider health,
licensing and exact source permissions *before* eligible=True is supplied.
"""
from __future__ import annotations

from typing import Any, Mapping
from math import isfinite
from urllib.parse import urlsplit, parse_qsl


_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "token", "access_token", "password",
    "secret", "authorization", "key", "appid",
})


def _public_tile_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("https://"):
        return False
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password or parsed.fragment):
            return False
        return all(key.lower() not in _SENSITIVE_KEYS
                   for key, _ in parse_qsl(parsed.query, keep_blank_values=True))
    except ValueError:
        return False


def make_mosaic_candidate(
    *,
    source_id: str,
    eligible: bool,
    machine_coverage: Mapping[str, Any] | None,
    payload: Mapping[str, Any],
    semantics: Mapping[str, Any],
    data_time: str | None,
    retrieved_at: str,
    routing_score: tuple[int, int, int] = (999, 999, 999),
) -> dict[str, Any] | None:
    """Turn already sanitized normalized raster resources into candidate data.

    Unknown coverage must not become global; URL exposure must already have
    passed the V1 public-URL sanitizer. Absence of image time is not filled
    from the retrieval clock. Timeline frames preserve independent timestamps.
    """
    if not eligible or not isinstance(source_id, str) or not source_id:
        return None
    if not isinstance(machine_coverage, Mapping):
        return None
    scope = machine_coverage.get("scope")
    if scope == "global":
        coverage = {"scope": "global"}
    elif scope == "bbox":
        box = machine_coverage.get("bbox")
        if not isinstance(box, Mapping):
            return None
        normalized: dict[str, float] = {}
        for key, low, high in (
            ("west", -180, 180), ("east", -180, 180),
            ("south", -90, 90), ("north", -90, 90),
        ):
            value = box.get(key)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not isfinite(value) or not low <= value <= high):
                return None
            normalized[key] = float(value)
        if (normalized["north"] <= normalized["south"]
                or normalized["west"] == normalized["east"]):
            return None
        coverage = {"scope": "bbox", "bbox": normalized}
    else:
        return None
    if not isinstance(payload, Mapping) or not isinstance(semantics, Mapping):
        return None
    tile_url = payload.get("tile_url")
    attribution = payload.get("attribution")
    legend = payload.get("legend")
    if not (_public_tile_url(tile_url)
            and isinstance(attribution, str) and attribution.strip()
            and isinstance(legend, Mapping)):
        return None
    required = ("quantity", "unit", "measurement_method", "observation_kind")
    if any(not isinstance(semantics.get(k), str) or not semantics[k].strip()
           for k in required):
        return None
    # The active Gewitterradar V2 consumer requires an explicit render contract.
    # Keep its values tied to the already normalized V1 raster descriptor.
    tile_size = payload.get("tile_size", 256)
    minimum = payload.get("min_zoom", 0)
    maximum = payload.get("max_zoom", 18)
    opacity = payload.get("default_opacity", 0.7)
    if type(tile_size) is not int or tile_size not in (128, 256, 512):
        return None
    if (any(isinstance(n, bool) or not isinstance(n, (int, float))
            or not isfinite(n) for n in (minimum, maximum, opacity))
            or not 0 <= minimum <= maximum <= 24
            or not 0 <= opacity <= 1):
        return None
    render = {
        "tile_size": tile_size,
        "min_zoom": float(minimum),
        "max_zoom": float(maximum),
        "opacity": float(opacity),
    }
    candidate = {
        "source_id": source_id,
        "eligible": True,
        "verified_coverage": True,
        "coverage": coverage,
        "resource_type": "raster_tile",
        "tile_url": tile_url,
        "data_time": data_time,
        "retrieved_at": retrieved_at,
        "attribution": attribution,
        "legend": dict(legend),
        "semantics": {k: semantics[k] for k in required},
        "routing_score": list(routing_score),
        "render": render,
    }
    timeline = payload.get("timeline")
    if isinstance(timeline, Mapping) and isinstance(timeline.get("frames"), list):
        if len(timeline["frames"]) > 24:
            return None
        frames = []
        for raw in timeline["frames"]:
            if not isinstance(raw, Mapping):
                continue
            frame_url = raw.get("tile_url")
            frame_time = raw.get("time")
            if (_public_tile_url(frame_url)
                    and isinstance(frame_time, str) and frame_time):
                frames.append({"tile_url": frame_url, "data_time": frame_time})
        if frames:
            candidate["frames"] = frames
    return candidate
