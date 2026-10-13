"""Shared WMS helpers for WeatherRouter satellite providers.

This module is intentionally small and provider-neutral. It is used by the NASA GIBS
and EUMETSAT adapters so both providers exercise the same raster/timeline contract.
DWD remains untouched in this block; it can be migrated to these helpers later only
after the new provider path has been proven in real Home Assistant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from time import monotonic
from typing import Any
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_CAPABILITIES_TTL_SECONDS = 300.0
_REQUEST_TIMEOUT_SECONDS = 25
_MAX_PARSED_TIMES = 4096

_capabilities_cache: dict[str, tuple[float, ET.Element]] = {}

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def local_name(tag: str) -> str:
    """Return an XML tag without namespace."""
    return tag.rsplit("}", 1)[-1]


def _parse_instant(value: str, now: datetime) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.lower() == "current":
        return now
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_duration(value: str) -> timedelta | None:
    match = _DURATION_RE.fullmatch(value.strip())
    if not match:
        return None
    result = timedelta(
        days=int(match.group("days") or 0),
        hours=int(match.group("hours") or 0),
        minutes=int(match.group("minutes") or 0),
        seconds=float(match.group("seconds") or 0),
    )
    return result if result.total_seconds() > 0 else None


def parse_time_axis(
    raw: str,
    now: datetime,
    *,
    max_points: int = _MAX_PARSED_TIMES,
) -> list[datetime]:
    """Parse WMS time dimensions while bounding very long historical intervals."""
    instants: set[datetime] = set()

    for token in raw.split(","):
        part = token.strip()
        if not part:
            continue

        interval = part.split("/")
        if len(interval) == 3:
            start = _parse_instant(interval[0], now)
            end = _parse_instant(interval[1], now)
            step = _parse_duration(interval[2])
            if start is None or end is None or step is None or end < start:
                continue

            total_steps = int((end - start) // step) + 1
            first_step = max(0, total_steps - max_points)
            for index in range(first_step, total_steps):
                value = start + step * index
                if value <= end:
                    instants.add(value)
            continue

        instant = _parse_instant(part, now)
        if instant is not None:
            instants.add(instant)

    ordered = sorted(instants)
    return ordered[-max_points:]


def find_layer(root: ET.Element, layer_name: str) -> ET.Element | None:
    """Find one named WMS Layer element."""
    for element in root.iter():
        if local_name(element.tag) != "Layer":
            continue
        for child in element:
            if local_name(child.tag) == "Name" and (child.text or "").strip() == layer_name:
                return element
    return None


def named_layer_names(root: ET.Element) -> list[str]:
    """Return sorted unique named WMS layers."""
    names: set[str] = set()
    for element in root.iter():
        if local_name(element.tag) != "Layer":
            continue
        for child in element:
            if local_name(child.tag) == "Name":
                name = (child.text or "").strip()
                if name:
                    names.add(name)
                break
    return sorted(names)


def layer_time_dimension(
    root: ET.Element,
    layer_name: str,
    now: datetime,
) -> tuple[list[datetime], str | None, str | None]:
    """Return time values, declared default and raw dimension text."""
    target = find_layer(root, layer_name)
    if target is None:
        raise ValueError(f"WMS layer not present in capabilities: {layer_name}")

    for element in target.iter():
        if local_name(element.tag) not in {"Dimension", "Extent"}:
            continue
        if element.attrib.get("name", "").lower() != "time":
            continue
        raw = (element.text or "").strip()
        return parse_time_axis(raw, now), element.attrib.get("default"), raw

    return [], None, None


def layer_style_metadata(root: ET.Element, layer_name: str) -> dict[str, Any]:
    """Return generic WMS style/legend metadata for one layer."""
    target = find_layer(root, layer_name)
    if target is None:
        return {"styles": [], "default_style": None, "legend_url": None}

    styles: list[dict[str, Any]] = []
    for child in target:
        if local_name(child.tag) != "Style":
            continue

        item: dict[str, Any] = {"name": None, "title": None, "legend_url": None}
        for element in child.iter():
            current = local_name(element.tag)
            if current == "Name" and item["name"] is None:
                item["name"] = (element.text or "").strip() or None
            elif current == "Title" and item["title"] is None:
                item["title"] = (element.text or "").strip() or None
            elif current == "OnlineResource" and item["legend_url"] is None:
                item["legend_url"] = (
                    element.attrib.get("{http://www.w3.org/1999/xlink}href")
                    or element.attrib.get("href")
                )
        styles.append(item)

    default = styles[0] if styles else None
    return {
        "styles": styles,
        "default_style": default.get("name") if default else None,
        "legend_url": default.get("legend_url") if default else None,
    }


async def async_capabilities(
    hass: HomeAssistant,
    endpoint: str,
    *,
    attempts: list[dict[str, Any]] | None = None,
) -> ET.Element:
    """Fetch and briefly cache one WMS 1.3.0 capabilities document."""
    now_mono = monotonic()
    cached = _capabilities_cache.get(endpoint)
    if cached is not None and now_mono < cached[0]:
        if attempts is not None:
            attempts.append(
                {
                    "endpoint": endpoint,
                    "stage": "capabilities_cache",
                    "cache_hit": True,
                    "ok": True,
                }
            )
        return cached[1]

    session = async_get_clientsession(hass)
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetCapabilities",
    }
    record: dict[str, Any] = {
        "endpoint": endpoint,
        "stage": "get_capabilities",
        "cache_hit": False,
    }
    try:
        async with session.get(
            endpoint,
            params=params,
            timeout=_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            record["http_status"] = response.status
            record["content_type"] = response.headers.get("Content-Type")
            payload = await response.read()
            record["bytes"] = len(payload)
            response.raise_for_status()
        root = ET.fromstring(payload)
        record["xml_root"] = local_name(root.tag)
        record["wms_version"] = root.attrib.get("version")
        record["ok"] = True
    except Exception as err:  # noqa: BLE001 - explicit provider isolation
        record["ok"] = False
        record["exception_type"] = type(err).__name__
        record["message"] = str(err)
        if attempts is not None:
            attempts.append(record)
        raise

    if attempts is not None:
        attempts.append(record)
    _capabilities_cache[endpoint] = (
        now_mono + _CAPABILITIES_TTL_SECONDS,
        root,
    )
    return root


def trim_observation_times(values: list[datetime], max_frames: int) -> list[datetime]:
    """Keep only the most recent observation frames."""
    if max_frames <= 0:
        return []
    return values[-max_frames:]


def iso_wms(value: datetime) -> str:
    """Return UTC ISO-8601 with seconds."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def time_parameter(value: datetime, mode: str) -> str:
    """Format a provider-compatible WMS TIME parameter."""
    if mode == "date":
        return value.astimezone(timezone.utc).date().isoformat()
    return iso_wms(value)


def tile_url(
    endpoint: str,
    layer_name: str,
    valid_time: datetime | None,
    *,
    time_mode: str = "datetime",
    style_name: str | None = None,
) -> str:
    """Build a MapLibre-compatible WMS 1.3.0 raster-tile request."""
    params: list[tuple[str, str]] = [
        ("service", "WMS"),
        ("version", "1.3.0"),
        ("request", "GetMap"),
        ("layers", layer_name),
        ("styles", style_name or ""),
        ("format", "image/png"),
        ("transparent", "true"),
        ("crs", "EPSG:3857"),
        ("width", "256"),
        ("height", "256"),
        ("bbox", "{bbox-epsg-3857}"),
    ]
    if valid_time is not None:
        params.append(("time", time_parameter(valid_time, time_mode)))
    return f"{endpoint}?{urlencode(params, safe='{}:,-')}"
