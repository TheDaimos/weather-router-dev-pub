"""Deutscher Wetterdienst WMS map-layer provider for WeatherRouter.

The adapter intentionally consumes the official DWD GeoServer WMS instead of parsing
RADOLAN/HDF5 files inside Home Assistant.  MapLibre can request WMS tiles directly with
its ``{bbox-epsg-3857}`` URL token, while the backend remains responsible for capability
discovery, time-axis parsing, provider metadata and failover host selection.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
import re
import zipfile
from time import monotonic
from typing import Any
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import (
    flood_semantics,
    geometry_intersects_bbox_strict,
    hail_hazard_match_scope,
    hail_semantic_class,
    normalize_hazard_type,
    normalize_severity,
    point_in_geometry,
    supercell_hazard_match_scope,
    supercell_semantic_class,
    tornado_hazard_match_scope,
    tornado_semantic_class,
    tropical_system_from_explicit_text,
    wind_hazard_match_scope,
    wind_hazard_semantic_class,
)
from ..spatial_coverage import wms_layer_geographic_coverage

_PRIMARY_WMS = "https://maps.dwd.de/geoserver/dwd/wms"
_BACKUP_WMS = "https://brz-maps.dwd.de/geoserver/dwd/wms"
_PRIMARY_GLOBAL_WMS = "https://maps.dwd.de/geoserver/ows"
_BACKUP_GLOBAL_WMS = "https://brz-maps.dwd.de/geoserver/ows"
_CAPABILITIES_TTL_SECONDS = 300.0
# Refresh proven geographic metadata before hard expiry, without treating old
# bounds as indefinitely valid or extending expiry without new source evidence.
_COVERAGE_REFRESH_LEAD_SECONDS = 90.0
_COVERAGE_REFRESH_RETRY_SECONDS = 30.0
_REQUEST_TIMEOUT_SECONDS = 20
_DWD_CAP_WARNINGS_URL = (
    "https://opendata.dwd.de/weather/alerts/cap/COMMUNEUNION_CELLS_STAT/"
    "Z_CAP_C_EDZW_LATEST_PVW_STATUS_PREMIUMCELLS_COMMUNEUNION_DE.zip"
)
_DWD_PROVIDER_REVISION = "wr-0.10.127-tropical-semantics-1"
_ICON_GLOBAL_REG025_LAYERS = frozenset(
    {
        "Icon_reg025_fd_sl_T2M",
        "Icon_reg025_fd_sl_UV10M",
    }
)
_ICON_GLOBAL_GRID_DOCUMENTATION = (
    "https://www.dwd.de/SharedDocs/downloads/DE/modelldokumentationen/"
    "nwv/icon_d2/icon_d2_dbbeschr_aktuell.pdf"
)


@dataclass(frozen=True, slots=True)
class _LayerSpec:
    capability_id: str
    name: str
    layer: str
    unit: str | None
    source_class: str
    default_opacity: float
    max_zoom: int
    max_frames: int


_LAYER_SPECS = (
    _LayerSpec(
        "radar_precipitation",
        "Niederschlagsradar · Analyse + Vorhersage",
        "Niederschlagsradar",
        "mm/h",
        "observation_forecast",
        0.72,
        11,
        72,
    ),
    _LayerSpec(
        "radar_precipitation_quality_checked",
        "Niederschlagsradar · qualitätsgeprüft (RY)",
        "RADOLAN-RY",
        None,
        "observation",
        0.68,
        11,
        48,
    ),
    _LayerSpec(
        "satellite_clouds",
        "METEOSAT · Wolken Tag/Nacht",
        "Satellite_meteosat_1km_euat_rgb_day_hrv_and_night_ir108_3h",
        None,
        "observation",
        0.74,
        9,
        36,
    ),
    _LayerSpec(
        "lightning_density",
        "Blitzdichte · NowCastMIX",
        "Blitzdichte",
        None,
        "observation",
        0.82,
        11,
        48,
    ),
    _LayerSpec(
        "thunderstorm_cells",
        "Gewitterzellen · NowCastMIX",
        "Gewitterzellen",
        None,
        "observation",
        0.9,
        11,
        48,
    ),
    _LayerSpec(
        "icon_eu_precipitation_1h",
        "ICON-EU · Niederschlag 1 h",
        "Icon-eu_reg00625_fd_sl_TOTPREC01H",
        "mm",
        "forecast",
        0.7,
        9,
        90,
    ),
    _LayerSpec(
        "icon_temperature_2m",
        "ICON · Temperatur 2 m",
        "Icon_reg025_fd_sl_T2M",
        "°C",
        "forecast",
        0.68,
        8,
        121,
    ),
    _LayerSpec(
        "icon_wind_10m",
        "ICON · Wind 10 m",
        "Icon_reg025_fd_sl_UV10M",
        "m/s",
        "forecast",
        0.72,
        8,
        121,
    ),
)

_CAPABILITY_MAP = {spec.capability_id: spec for spec in _LAYER_SPECS}
_CAPABILITIES = tuple(
    CapabilityInfo(
        spec.capability_id,
        spec.name,
        spec.unit,
        spec.source_class,
        "raster_tile",
    )
    for spec in _LAYER_SPECS
) + (
    CapabilityInfo(
        id="official_weather_warnings",
        name="Amtliche Wetterwarnungen · DWD",
        unit=None,
        source_class="warning",
        render_mode="hazard_feed",
        description=(
            "Aktive amtliche DWD-Warnungen, normalisiert für WeatherRouter und "
            "spätere Consumer wie Gewitterradar."
        ),
        coverage="Deutschland",
        temporal_resolution="ereignisgesteuert / nahezu Echtzeit",
        strengths=(
            "amtliche deutsche Warnquelle",
            "Gewitter, Sturm/Orkan, Starkregen, Hagel und weitere Warnereignisse",
            "CAP-Polygongeometrien, WarnCellID und amtliche Warnstufen",
        ),
        limitations=(
            "Ereignisgeometrie ist an die jeweils im amtlichen CAP-Statusfeed "
            "veröffentlichte Warnfläche gebunden",
        ),
        documentation_url="https://www.dwd.de/DE/leistungen/warnungen/warnungen.html",
    ),
)

_cached_root: ET.Element | None = None
_cached_wms_base: str | None = None
_cache_valid_until = 0.0
_cache_loaded_at = 0.0

# Layer-specific GetCapabilities is a fallback only when the aggregate DWD WMS
# does not expose a usable geographic bbox on the concrete named layer.
# Entries are bounded by the same short TTL as the aggregate capabilities cache.
_layer_coverage_cache: dict[str, dict[str, Any]] = {}

# WMS GetCapabilities can take longer than a V2 consumer's six-second
# preflight budget. Coalesce repeated requests, and let the one bounded
# provider task finish even when an individual consumer cancels its wait.
# This cache stores proven layer coverage only, never a guessed extent.
_capabilities_inflight_loop: asyncio.AbstractEventLoop | None = None
_capabilities_inflight: asyncio.Task[tuple[str, ET.Element]] | None = None
_coverage_inflight_loop: asyncio.AbstractEventLoop | None = None
_coverage_inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}
_coverage_result_cache: dict[str, dict[str, Any]] = {}
_coverage_refresh_last_started: dict[str, float] = {}
_coverage_failure_retry_until: dict[str, float] = {}
_coverage_lookup_stage: dict[str, str] = {}
# The worldwide WMS fallback is one service document shared by all DWD layers.
_global_wms_cache: dict[str, dict[str, Any]] = {}
_global_wms_inflight_loop: asyncio.AbstractEventLoop | None = None
_global_wms_inflight: dict[str, asyncio.Task[dict[str, Any]]] = {}


def _observe_background_result(task: asyncio.Task[Any]) -> None:
    """Retrieve errors from intentionally shielded, finite provider tasks."""
    if not task.cancelled():
        try:
            task.exception()
        except Exception:  # noqa: BLE001 - error returned to future clients
            pass


def _cached_coverage_result(layer: str, now: float) -> dict[str, Any] | None:
    """Only reuse successfully verified geographic layer metadata."""
    entry = _coverage_result_cache.get(layer)
    if not isinstance(entry, dict) or now >= entry.get("valid_until", 0.0):
        return None
    coverage = entry.get("coverage")
    if not isinstance(coverage, dict):
        return None
    result = dict(coverage)
    cache = dict(result.get("cache") or {})
    cache.update({
        "type": "wms_verified_layer_coverage",
        "layer": layer,
        "populated": True,
        "valid": True,
        "hit": True,
        "age_seconds": round(max(0.0, now - entry["loaded_at"]), 3),
        "ttl_seconds": _CAPABILITIES_TTL_SECONDS,
        "ttl_remaining_seconds": round(max(0.0, entry["valid_until"] - now), 3),
    })
    result["cache"] = cache
    return result

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def _local_name(tag: str) -> str:
    """Return the namespace-free XML local name."""
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str | None:
    """Return stripped text of the first direct child with one local name."""
    for child in element:
        if _local_name(child.tag) == name:
            text = (child.text or "").strip()
            return text or None
    return None


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    """Return direct XML children with the requested local name."""
    return [child for child in element if _local_name(child.tag) == name]


def _parse_cap_ring(value: str | None) -> list[list[float]] | None:
    """Convert CAP latitude,longitude pairs into one GeoJSON linear ring."""
    if not value:
        return None
    ring: list[list[float]] = []
    for token in value.split():
        if "," not in token:
            continue
        latitude_text, longitude_text = token.split(",", 1)
        try:
            latitude = float(latitude_text)
            longitude = float(longitude_text)
        except ValueError:
            continue
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            continue
        ring.append([longitude, latitude])
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring if len(ring) >= 4 else None


def _cap_info(root: ET.Element) -> ET.Element | None:
    """Select German CAP info when present, otherwise the first info block."""
    infos = _children(root, "info")
    if not infos:
        return None
    for info in infos:
        language = (_child_text(info, "language") or "").casefold()
        if language.startswith("de"):
            return info
    return infos[0]


def _cap_geometry_and_areas(
    info: ET.Element,
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    """Return event geometry, area descriptions and DWD WarnCellIDs."""
    polygons: list[list[list[list[float]]]] = []
    area_descriptions: list[str] = []
    warncell_ids: list[str] = []

    for area in _children(info, "area"):
        area_desc = _child_text(area, "areaDesc")
        if area_desc:
            area_descriptions.append(area_desc)

        exclusions: list[list[float]] = []
        for geocode in _children(area, "geocode"):
            value_name = (_child_text(geocode, "valueName") or "").strip()
            value = (_child_text(geocode, "value") or "").strip()
            if value_name == "WARNCELLID" and value:
                warncell_ids.append(value)
            elif value_name == "EXCLUDE_POLYGON":
                ring = _parse_cap_ring(value)
                if ring is not None:
                    exclusions.append(ring)

        area_polygons = [
            ring
            for polygon in _children(area, "polygon")
            if (ring := _parse_cap_ring((polygon.text or "").strip())) is not None
        ]
        for outer in area_polygons:
            # CAP-DWD permits EXCLUDE_POLYGON holes alongside exactly one polygon
            # in the containing area block.
            polygons.append([outer, *exclusions])

    unique_areas = list(dict.fromkeys(area_descriptions))
    unique_warncells = list(dict.fromkeys(warncell_ids))
    if not polygons:
        return None, unique_areas, unique_warncells
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}, unique_areas, unique_warncells
    return {"type": "MultiPolygon", "coordinates": polygons}, unique_areas, unique_warncells


def _cap_parameters(info: ET.Element) -> dict[str, Any]:
    """Return CAP parameter value pairs without inventing missing fields."""
    result: dict[str, Any] = {}
    for parameter in _children(info, "parameter"):
        name = _child_text(parameter, "valueName")
        value = _child_text(parameter, "value")
        if name and value is not None:
            result[name] = value
    return result


def _parse_dwd_cap_alert(root: ET.Element) -> dict[str, Any] | None:
    """Normalize one CAP-DWD alert into a WeatherRouter provider event."""
    if _local_name(root.tag) != "alert":
        return None
    info = _cap_info(root)
    if info is None:
        return None

    status = (_child_text(root, "status") or "").strip()
    message_type = (_child_text(root, "msgType") or "").strip()
    if status and status.casefold() != "actual":
        return None
    if message_type.casefold() == "cancel":
        return None

    event_name = _child_text(info, "event")
    headline = _child_text(info, "headline")
    description = _child_text(info, "description")
    instruction = _child_text(info, "instruction")
    geometry, area_descriptions, warncell_ids = _cap_geometry_and_areas(info)

    identifier = _child_text(root, "identifier")
    if not identifier:
        identifier = "|".join(
            str(item or "")
            for item in (
                _child_text(root, "sent"),
                event_name,
                headline,
                _child_text(info, "onset"),
                _child_text(info, "expires"),
            )
        )
    event_id = f"dwd:{identifier}"

    parameters = _cap_parameters(info)
    if warncell_ids:
        parameters["warncell_ids"] = warncell_ids
    parameters["cap_sender"] = _child_text(root, "sender")
    parameters["cap_geometry_source"] = (
        "COMMUNEUNION_CELLS_STAT" if geometry is not None else None
    )

    response_types = [
        (child.text or "").strip()
        for child in _children(info, "responseType")
        if (child.text or "").strip()
    ]
    hazard_type = normalize_hazard_type(
        event_name,
        headline,
        description,
        instruction,
    )
    event_payload: dict[str, Any] = {
        "id": event_id,
        "hazard_type": hazard_type,
        "event": event_name,
        "headline": headline,
        "severity": normalize_severity(_child_text(info, "severity")),
        "urgency": _child_text(info, "urgency"),
        "certainty": _child_text(info, "certainty"),
        "status": status.casefold() or None,
        "message_type": message_type.casefold() or None,
        "sent": _child_text(root, "sent"),
        "effective": _child_text(info, "effective"),
        "onset": _child_text(info, "onset"),
        "expires": _child_text(info, "expires"),
        "ends": _child_text(info, "expires"),
        "area_desc": "; ".join(area_descriptions) or None,
        "geometry": geometry,
        "description": description,
        "instruction": instruction,
        "sender_name": _child_text(info, "senderName") or "Deutscher Wetterdienst (DWD)",
        "response": response_types[0] if response_types else None,
        "affected_zones": warncell_ids,
        "parameters": parameters,
        "web_url": "https://www.dwd.de/warnungen",
    }
    semantic_class = tornado_semantic_class(hazard_type)
    if semantic_class is not None:
        event_payload.update(
            {
                "tornado_semantic_class": semantic_class,
                "alert_stage": "warning",
                "hazard_match_scope": tornado_hazard_match_scope(
                    hazard_type,
                    event=event_name,
                    headline=headline,
                    description=description,
                    instruction=instruction,
                ),
            }
        )

    hail_class = hail_semantic_class(
        event_name,
        headline,
        description,
        instruction,
    )
    if hail_class is not None:
        event_payload.update(
            {
                "hail_semantic_class": hail_class,
                "hail_match_scope": hail_hazard_match_scope(
                    event=event_name,
                    headline=headline,
                    description=description,
                    instruction=instruction,
                ),
            }
        )
        event_payload.setdefault("alert_stage", "warning")

    wind_hazard_class = wind_hazard_semantic_class(
        event_name,
        headline,
        description,
        instruction,
    )
    if wind_hazard_class is not None:
        event_payload.update(
            {
                "wind_hazard_semantic_class": wind_hazard_class,
                "wind_hazard_match_scope": wind_hazard_match_scope(
                    event=event_name,
                    headline=headline,
                    description=description,
                    instruction=instruction,
                ),
            }
        )
        event_payload.setdefault("alert_stage", "warning")

    supercell_class = supercell_semantic_class(
        event_name,
        headline,
        description,
        instruction,
    )
    if supercell_class is not None:
        event_payload.update(
            {
                "supercell_semantic_class": supercell_class,
                "supercell_match_scope": supercell_hazard_match_scope(
                    event=event_name,
                    headline=headline,
                    description=description,
                    instruction=instruction,
                ),
            }
        )
        event_payload.setdefault("alert_stage", "warning")

    flood_matches = flood_semantics(
        event=event_name,
        headline=headline,
        description=description,
        instruction=instruction,
    )
    if flood_matches:
        event_payload["flood_semantics"] = flood_matches
        event_payload.setdefault("alert_stage", "warning")

    tropical_system = tropical_system_from_explicit_text(
        event_name,
        headline,
    )
    if tropical_system is not None:
        event_payload["tropical_system"] = tropical_system
    return event_payload


def _parse_dwd_cap_zip(payload: bytes) -> dict[str, Any]:
    """Parse the official bounded CAP ZIP outside Home Assistant's event loop."""
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) > 5000:
            raise ValueError("DWD CAP ZIP contains too many members")
        if sum(max(0, item.file_size) for item in members) > 25 * 1024 * 1024:
            raise ValueError("DWD CAP ZIP expands beyond the safety limit")

        events: list[dict[str, Any]] = []
        invalid_xml_count = 0
        parsed_alert_count = 0
        for member in members:
            try:
                root = ET.fromstring(archive.read(member))
            except (ET.ParseError, OSError, RuntimeError):
                invalid_xml_count += 1
                continue
            event = _parse_dwd_cap_alert(root)
            if event is None:
                continue
            parsed_alert_count += 1
            events.append(event)

    return {
        "events": events,
        "zip_member_count": len(members),
        "parsed_alert_count": parsed_alert_count,
        "invalid_xml_count": invalid_xml_count,
        "geometry_event_count": sum(
            1 for event in events if isinstance(event.get("geometry"), dict)
        ),
    }


def _filter_dwd_cap_events(
    events: list[dict[str, Any]],
    *,
    latitude: float | None,
    longitude: float | None,
    bbox: tuple[float, float, float, float] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply fail-closed Point/BBox filtering to DWD CAP event geometry."""
    mode = "global"
    if latitude is not None and longitude is not None:
        mode = "point"
    elif bbox is not None:
        mode = "bbox"

    matched: list[dict[str, Any]] = []
    missing_geometry = 0
    for event in events:
        geometry = event.get("geometry") if isinstance(event.get("geometry"), dict) else None
        if mode == "global":
            matched.append(event)
            continue
        if geometry is None:
            missing_geometry += 1
            continue
        if mode == "point":
            if point_in_geometry(geometry, float(longitude), float(latitude)):
                matched.append(event)
        elif geometry_intersects_bbox_strict(geometry, bbox):
            matched.append(event)

    matched_count = len(matched)
    return matched, {
        "mode": mode,
        "input_event_count": len(events),
        "matched_event_count": matched_count,
        "geometry_event_count": sum(
            1 for event in events if isinstance(event.get("geometry"), dict)
        ),
        "excluded_missing_geometry": missing_geometry,
        "event_relevance_evidence": (
            "runtime_event_geometry"
            if mode in {"point", "bbox"}
            else "official_cap_status_feed"
        ),
        "authority_coverage_status": (
            "event_match_proven"
            if mode in {"point", "bbox"} and matched_count > 0
            else "unknown"
            if mode in {"point", "bbox"}
            else "regional_declared"
        ),
        "zero_matches_mean": (
            "no_active_matching_warning_not_outside_coverage"
            if mode in {"point", "bbox"} and matched_count == 0
            else None
        ),
    }


def _parse_instant(value: str) -> datetime | None:
    """Parse one ISO-8601 instant from a WMS time dimension."""
    text = value.strip()
    if not text or text.lower() == "current":
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _parse_duration(value: str) -> timedelta | None:
    """Parse the simple ISO-8601 durations used by DWD WMS time axes."""
    match = _DURATION_RE.fullmatch(value.strip())
    if not match:
        return None
    duration = timedelta(
        days=int(match.group("days") or 0),
        hours=int(match.group("hours") or 0),
        minutes=int(match.group("minutes") or 0),
        seconds=float(match.group("seconds") or 0),
    )
    return duration if duration.total_seconds() > 0 else None


def _time_axis(raw: str) -> list[datetime]:
    """Expand a WMS time dimension into ordered unique instants."""
    instants: set[datetime] = set()
    for token in raw.split(","):
        part = token.strip()
        if not part:
            continue
        interval = part.split("/")
        if len(interval) == 3:
            start = _parse_instant(interval[0])
            end = _parse_instant(interval[1])
            step = _parse_duration(interval[2])
            if start is None or end is None or step is None or end < start:
                continue
            current = start
            # Guard against malformed capabilities creating an unbounded expansion.
            for _ in range(5000):
                if current > end:
                    break
                instants.add(current)
                current += step
            continue

        instant = _parse_instant(part)
        if instant is not None:
            instants.add(instant)

    return sorted(instants)


def _layer_time_dimension(root: ET.Element, layer_name: str) -> tuple[list[datetime], str | None]:
    """Return time values and declared default for one named WMS layer."""
    target: ET.Element | None = None
    for element in root.iter():
        if _local_name(element.tag) != "Layer":
            continue
        for child in element:
            if _local_name(child.tag) == "Name" and (child.text or "").strip() == layer_name:
                target = element
                break
        if target is not None:
            break

    if target is None:
        raise ValueError(f"DWD WMS layer not present in capabilities: {layer_name}")

    for element in target.iter():
        if _local_name(element.tag) not in {"Dimension", "Extent"}:
            continue
        if element.attrib.get("name", "").lower() != "time":
            continue
        raw = (element.text or "").strip()
        return _time_axis(raw), element.attrib.get("default")

    return [], None



def _capabilities_cache_diagnostic(now: float | None = None) -> dict[str, Any]:
    """Return bounded DWD WMS cache metadata without exposing URLs."""
    current = monotonic() if now is None else now
    populated = _cached_root is not None and _cached_wms_base is not None
    valid = populated and current < _cache_valid_until
    age = current - _cache_loaded_at if populated and _cache_loaded_at > 0 else None
    return {
        "type": "wms_get_capabilities",
        "populated": populated,
        "valid": valid,
        "hit": valid,
        "age_seconds": round(max(0.0, age), 3) if age is not None else None,
        "ttl_seconds": _CAPABILITIES_TTL_SECONDS,
        "ttl_remaining_seconds": round(max(0.0, _cache_valid_until - current), 3)
        if populated else None,
        "endpoint_host": urlsplit(_cached_wms_base).hostname
        if _cached_wms_base else None,
    }


async def _parse_wms_document(
    hass: HomeAssistant, payload: bytes,
) -> ET.Element:
    """Keep large provider XML parsing off the Home Assistant event loop."""
    executor = getattr(hass, "async_add_executor_job", None)
    if callable(executor) and len(payload) >= 65536:
        return await executor(ET.fromstring, payload)
    return ET.fromstring(payload)


async def _wms_layer_coverage(
    hass: HomeAssistant, root: ET.Element, layer: str,
) -> dict[str, Any] | None:
    """Inspect provider XML without blocking HA for large layer collections."""
    executor = getattr(hass, "async_add_executor_job", None)
    if callable(executor):
        return await executor(wms_layer_geographic_coverage, root, layer)
    return wms_layer_geographic_coverage(root, layer)


async def _wms_named_layers(
    hass: HomeAssistant, root: ET.Element,
) -> list[str]:
    executor = getattr(hass, "async_add_executor_job", None)
    if callable(executor):
        return await executor(_named_layer_names, root)
    return _named_layer_names(root)


async def _fetch_capabilities_uncached(
    hass: HomeAssistant,
    attempts: list[dict[str, Any]] | None = None,
    *,
    force_fetch: bool = False,
) -> tuple[str, ET.Element]:
    """Fetch/cache DWD WMS capabilities and optionally record diagnostic stages."""
    global _cached_root, _cached_wms_base, _cache_valid_until, _cache_loaded_at

    now = monotonic()
    if (
        _cached_root is not None and _cached_wms_base is not None
        and now < _cache_valid_until and not force_fetch
    ):
        if attempts is not None:
            attempts.append(
                {
                    "endpoint": _cached_wms_base,
                    "cache_hit": True,
                    "ok": True,
                    "stage": "capabilities_cache",
                    "cache": _capabilities_cache_diagnostic(now),
                }
            )
        return _cached_wms_base, _cached_root

    session = async_get_clientsession(hass)
    last_error: Exception | None = None
    for base in (_PRIMARY_WMS, _BACKUP_WMS):
        params = {
            "service": "WMS",
            "version": "1.3.0",
            "request": "GetCapabilities",
        }
        record: dict[str, Any] = {
            "endpoint": base,
            "cache_hit": False,
            "stage": "get_capabilities",
        }
        try:
            async with session.get(base, params=params, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                record["http_status"] = response.status
                record["content_type"] = response.headers.get("Content-Type")
                payload = await response.read()
                record["bytes"] = len(payload)
                response.raise_for_status()
            root = await _parse_wms_document(hass, payload)
            record["xml_root"] = _local_name(root.tag)
            record["wms_version"] = root.attrib.get("version")
            record["ok"] = True
        except Exception as err:  # noqa: BLE001 - provider host failover is intentional
            record["ok"] = False
            record["exception_type"] = type(err).__name__
            record["message"] = str(err)
            if attempts is not None:
                attempts.append(record)
            last_error = err
            continue

        if attempts is not None:
            attempts.append(record)
        _cached_root = root
        _cached_wms_base = base
        _cache_loaded_at = monotonic()
        _cache_valid_until = _cache_loaded_at + _CAPABILITIES_TTL_SECONDS
        return base, root

    raise ValueError("DWD WMS capabilities are unavailable") from last_error


async def _async_capabilities(
    hass: HomeAssistant,
    attempts: list[dict[str, Any]] | None = None,
    *,
    refresh_if_aging: bool = False,
) -> tuple[str, ET.Element]:
    """One shared WMS metadata fetch across concurrent DWD layer requests.

    The individual V2 wait_for may expire; shield keeps the already-started
    bounded network operation alive to populate the normal five-minute cache.
    V1 continues to use exactly the same provider metadata and time axis.
    """
    global _capabilities_inflight_loop, _capabilities_inflight
    now = monotonic()
    if (
        _cached_root is not None and _cached_wms_base is not None
        and now < _cache_valid_until
        and (not refresh_if_aging
             or _cache_valid_until - now > _COVERAGE_REFRESH_LEAD_SECONDS)
    ):
        if attempts is not None:
            attempts.append({
                "stage": "capabilities_cache",
                "cache_hit": True,
                "ok": True,
                "cache": _capabilities_cache_diagnostic(now),
            })
        return _cached_wms_base, _cached_root

    loop = asyncio.get_running_loop()
    if _capabilities_inflight_loop is not loop:
        _capabilities_inflight_loop = loop
        _capabilities_inflight = None
    if _capabilities_inflight is None or _capabilities_inflight.done():
        _capabilities_inflight = loop.create_task(
            _fetch_capabilities_uncached(hass, force_fetch=refresh_if_aging),
            name="wr-dwd-wms-capabilities",
        )
        _capabilities_inflight.add_done_callback(_observe_background_result)
    elif attempts is not None:
        attempts.append({"stage": "capabilities_shared_inflight", "cache_hit": False})
    return await asyncio.shield(_capabilities_inflight)


def _layer_capabilities_endpoint(base: str, layer: str) -> str:
    """Return DWD GeoServer's layer-scoped WMS endpoint without query data."""
    parsed = urlsplit(base)
    path = parsed.path.rstrip("/")
    if path.endswith("/wms"):
        path = path[:-4]
    scoped_path = f"{path}/{quote(layer, safe='')}/wms"
    return urlunsplit((parsed.scheme, parsed.netloc, scoped_path, "", ""))


def _layer_coverage_cache_diagnostic(
    layer: str,
    now: float | None = None,
) -> dict[str, Any]:
    """Return bounded cache metadata for one layer-specific capabilities result."""
    current = monotonic() if now is None else now
    entry = _layer_coverage_cache.get(layer)
    populated = isinstance(entry, dict)
    valid_until = float(entry.get("valid_until", 0.0)) if populated else 0.0
    loaded_at = float(entry.get("loaded_at", 0.0)) if populated else 0.0
    valid = populated and current < valid_until
    age = current - loaded_at if populated and loaded_at > 0 else None
    endpoint = str(entry.get("endpoint") or "") if populated else ""
    return {
        "type": "wms_layer_get_capabilities",
        "layer": layer,
        "populated": populated,
        "valid": valid,
        "hit": valid,
        "age_seconds": round(max(0.0, age), 3) if age is not None else None,
        "ttl_seconds": _CAPABILITIES_TTL_SECONDS,
        "ttl_remaining_seconds": round(max(0.0, valid_until - current), 3)
        if populated else None,
        "endpoint_host": urlsplit(endpoint).hostname if endpoint else None,
    }


def _documented_icon_global_grid_coverage(
    layer: str,
    attempts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return DWD's documented global ICON grid after runtime layer presence proof.

    WMS endpoint reachability alone is deliberately not treated as coverage. This
    fallback is allowed only for an explicit known ICON global regular-grid layer
    and only after the current DWD global GetCapabilities response confirmed that
    the concrete layer is actually present.
    """
    if layer not in _ICON_GLOBAL_REG025_LAYERS:
        return None

    presence: dict[str, Any] | None = None
    for item in attempts:
        if (
            item.get("stage") == "global_wms_get_capabilities"
            and item.get("http_status") == 200
            and item.get("target_present") is True
        ):
            presence = item
            break
    if presence is None:
        return None

    endpoint = str(presence.get("endpoint") or "")
    return {
        "scope": "global",
        "source": "dwd_official_model_grid_contract",
        "provider_metadata_source": (
            "DWD ICON global regular latitude-longitude grid definition"
        ),
        "coverage_metadata_scope": "documented_model_grid",
        "layer": layer,
        "model": "ICON global",
        "model_grid": "regular_latlon_0.25_degree",
        "model_grid_documented_extent": {
            "longitude": "0.0..359.75 degrees",
            "latitude": "-90.0..90.0 degrees",
        },
        "documentation_url": _ICON_GLOBAL_GRID_DOCUMENTATION,
        "runtime_layer_presence_verified": True,
        "runtime_layer_presence_endpoint_host": (
            urlsplit(endpoint).hostname if endpoint else None
        ),
        "endpoint_reachability_is_coverage": False,
        "coverage_basis": (
            "official_model_grid_contract_plus_runtime_wms_layer_presence"
        ),
    }


async def _shared_global_wms_root(
    hass: HomeAssistant, endpoint: str, *, refresh_if_aging: bool = False,
) -> tuple[ET.Element, dict[str, Any], bool]:
    """Fetch the canonical WMS document once per host and event loop.

    Keep valid parsed provider metadata for five minutes, not inferred bbox
    claims. A layer must still prove its own named geographic footprint.
    """
    global _global_wms_inflight_loop
    now = monotonic()
    cached = _global_wms_cache.get(endpoint)
    if (
        isinstance(cached, dict) and now < cached.get("valid_until", 0.0)
        and (not refresh_if_aging or cached["valid_until"] - now
             > _COVERAGE_REFRESH_LEAD_SECONDS)
    ):
        return cached["root"], dict(cached["metadata"]), True

    loop = asyncio.get_running_loop()
    if _global_wms_inflight_loop is not loop:
        _global_wms_inflight_loop = loop
        _global_wms_inflight.clear()
    task = _global_wms_inflight.get(endpoint)
    if task is None or task.done():
        async def _load() -> dict[str, Any]:
            session = async_get_clientsession(hass)
            async with session.get(
                endpoint,
                params={
                    "service": "WMS",
                    "version": "1.3.0",
                    "request": "GetCapabilities",
                },
                timeout=_REQUEST_TIMEOUT_SECONDS,
            ) as response:
                metadata = {
                    "http_status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                }
                payload = await response.read()
                metadata["bytes"] = len(payload)
                response.raise_for_status()
            root = await _parse_wms_document(hass, payload)
            entry = {
                "root": root,
                "metadata": metadata,
                "valid_until": monotonic() + _CAPABILITIES_TTL_SECONDS,
            }
            _global_wms_cache[endpoint] = entry
            return entry

        task = loop.create_task(_load(), name="wr-dwd-global-wms-metadata")
        task.add_done_callback(_observe_background_result)
        _global_wms_inflight[endpoint] = task
    entry = await asyncio.shield(task)
    return entry["root"], dict(entry["metadata"]), False


async def _async_global_wms_coverage(
    hass: HomeAssistant,
    layer: str,
    *,
    attempts: list[dict[str, Any]] | None = None,
    refresh_if_aging: bool = False,
) -> dict[str, Any]:
    """Resolve one layer bbox from DWD's canonical global GeoServer WMS."""
    now = monotonic()
    cached = _layer_coverage_cache.get(layer)
    if (
        isinstance(cached, dict)
        and now < float(cached.get("valid_until", 0.0))
        and isinstance(cached.get("coverage"), dict)
        and cached["coverage"].get("coverage_metadata_scope") == "global_wms_layer"
        and (not refresh_if_aging
             or float(cached["valid_until"]) - now > _COVERAGE_REFRESH_LEAD_SECONDS)
    ):
        result = dict(cached["coverage"])
        cache = _layer_coverage_cache_diagnostic(layer, now)
        cache["hit"] = True
        result["cache"] = cache
        return result

    last_error: Exception | None = None
    for endpoint in (_PRIMARY_GLOBAL_WMS, _BACKUP_GLOBAL_WMS):
        record: dict[str, Any] = {
            "stage": "global_wms_get_capabilities",
            "layer": layer,
            "endpoint": endpoint,
            "cache_hit": False,
        }
        try:
            root, metadata, was_cached = await _shared_global_wms_root(
                hass, endpoint, refresh_if_aging=refresh_if_aging
            )
            record.update(metadata)
            record["cache_hit"] = was_cached
            names = await _wms_named_layers(hass, root)
            record["xml_root"] = _local_name(root.tag)
            record["wms_version"] = root.attrib.get("version")
            record["named_layer_count"] = len(names)
            record["target_present"] = (
                layer in names
                or any(name.rsplit(":", 1)[-1] == layer for name in names)
            )

            coverage = await _wms_layer_coverage(hass, root, layer)
            if coverage is None:
                raise ValueError(
                    "global DWD WMS contains no usable machine-readable "
                    f"geographic coverage for {layer}"
                )

            result = dict(coverage)
            result["provider_metadata_source"] = (
                "DWD global WMS GetCapabilities"
            )
            result["coverage_metadata_scope"] = "global_wms_layer"
            result["endpoint_host"] = urlsplit(endpoint).hostname
            result["aggregate_coverage_missing"] = True

            _layer_coverage_cache[layer] = {
                "coverage": dict(result),
                "endpoint": endpoint,
                "loaded_at": now,
                "valid_until": now + _CAPABILITIES_TTL_SECONDS,
            }
            cache = _layer_coverage_cache_diagnostic(layer, now)
            cache["hit"] = False
            result["cache"] = cache

            record["ok"] = True
            record["coverage_source"] = result.get("bbox_source")
            record["bbox_inherited"] = result.get("bbox_inherited")
            record["bbox_inherited_from"] = result.get("bbox_inherited_from")
            if attempts is not None:
                attempts.append(record)
            return result
        except Exception as err:  # noqa: BLE001 - provider failover is intentional
            record["ok"] = False
            record["exception_type"] = type(err).__name__
            record["message"] = str(err)
            if attempts is not None:
                attempts.append(record)
            last_error = err

    raise ValueError(
        f"DWD global WMS coverage is unavailable: {layer}"
    ) from last_error


async def _async_layer_specific_coverage(
    hass: HomeAssistant,
    layer: str,
    *,
    preferred_base: str | None = None,
    attempts: list[dict[str, Any]] | None = None,
    refresh_if_aging: bool = False,
) -> dict[str, Any]:
    """Resolve/cache coverage from DWD's layer-scoped GeoServer service."""
    now = monotonic()
    cached = _layer_coverage_cache.get(layer)
    if (
        isinstance(cached, dict)
        and now < float(cached.get("valid_until", 0.0))
        and isinstance(cached.get("coverage"), dict)
        and (not refresh_if_aging
             or float(cached["valid_until"]) - now > _COVERAGE_REFRESH_LEAD_SECONDS)
    ):
        result = dict(cached["coverage"])
        cache = _layer_coverage_cache_diagnostic(layer, now)
        cache["hit"] = True
        result["cache"] = cache
        if attempts is not None:
            attempts.append(
                {
                    "stage": "layer_coverage_cache",
                    "layer": layer,
                    "cache_hit": True,
                    "ok": True,
                    "cache": cache,
                }
            )
        return result

    bases: list[str] = []
    for base in (preferred_base, _PRIMARY_WMS, _BACKUP_WMS):
        if isinstance(base, str) and base and base not in bases:
            bases.append(base)

    session = async_get_clientsession(hass)
    last_error: Exception | None = None
    for base in bases:
        endpoint = _layer_capabilities_endpoint(base, layer)
        record: dict[str, Any] = {
            "stage": "layer_get_capabilities",
            "layer": layer,
            "endpoint": endpoint,
            "cache_hit": False,
        }
        try:
            async with session.get(
                endpoint,
                params={
                    "service": "WMS",
                    "version": "1.3.0",
                    "request": "GetCapabilities",
                },
                timeout=_REQUEST_TIMEOUT_SECONDS,
            ) as response:
                record["http_status"] = response.status
                record["content_type"] = response.headers.get("Content-Type")
                payload = await response.read()
                record["bytes"] = len(payload)
                response.raise_for_status()
            root = await _parse_wms_document(hass, payload)
            record["xml_root"] = _local_name(root.tag)
            record["wms_version"] = root.attrib.get("version")
            coverage = await _wms_layer_coverage(hass, root, layer)
            if coverage is None:
                raise ValueError(
                    f"DWD layer-specific WMS has no machine-readable geographic coverage: {layer}"
                )

            result = dict(coverage)
            result["provider_metadata_source"] = (
                "DWD layer-specific WMS GetCapabilities"
            )
            result["coverage_metadata_scope"] = "layer_specific_wms"
            result["endpoint_host"] = urlsplit(endpoint).hostname
            result["aggregate_coverage_missing"] = True

            _layer_coverage_cache[layer] = {
                "coverage": dict(result),
                "endpoint": endpoint,
                "loaded_at": now,
                "valid_until": now + _CAPABILITIES_TTL_SECONDS,
            }
            cache = _layer_coverage_cache_diagnostic(layer, now)
            cache["hit"] = False
            result["cache"] = cache
            record["ok"] = True
            record["coverage_source"] = result.get("bbox_source")
            if attempts is not None:
                attempts.append(record)
            return result
        except Exception as err:  # noqa: BLE001 - provider failover is intentional
            record["ok"] = False
            record["exception_type"] = type(err).__name__
            record["message"] = str(err)
            if attempts is not None:
                attempts.append(record)
            last_error = err

    raise ValueError(
        f"DWD layer-specific WMS coverage is unavailable: {layer}"
    ) from last_error


def _named_layer_names(root: ET.Element) -> list[str]:
    """Return sorted unique WMS layer names from one capabilities document."""
    names: set[str] = set()
    for element in root.iter():
        if _local_name(element.tag) != "Layer":
            continue
        for child in element:
            if _local_name(child.tag) != "Name":
                continue
            name = (child.text or "").strip()
            if name:
                names.add(name)
            break
    return sorted(names)


def _layer_style_metadata(root: ET.Element, layer_name: str) -> dict[str, Any]:
    """Return style and legend metadata for one named WMS layer."""
    target: ET.Element | None = None
    for element in root.iter():
        if _local_name(element.tag) != "Layer":
            continue
        for child in element:
            if _local_name(child.tag) == "Name" and (child.text or "").strip() == layer_name:
                target = element
                break
        if target is not None:
            break

    if target is None:
        return {"styles": [], "default_style": None, "legend_url": None}

    styles: list[dict[str, Any]] = []
    for child in target:
        if _local_name(child.tag) != "Style":
            continue

        item: dict[str, Any] = {
            "name": None,
            "title": None,
            "legend_url": None,
        }
        for element in child.iter():
            local = _local_name(element.tag)
            if local == "Name" and item["name"] is None:
                item["name"] = (element.text or "").strip() or None
            elif local == "Title" and item["title"] is None:
                item["title"] = (element.text or "").strip() or None
            elif local == "OnlineResource" and item["legend_url"] is None:
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


def _legend_url(base: str, layer: str, style_name: str | None) -> str:
    """Build a provider-side generic WMS legend URL when capabilities omit one."""
    params: list[tuple[str, str]] = [
        ("service", "WMS"),
        ("version", "1.1.1"),
        ("request", "GetLegendGraphic"),
        ("format", "image/png"),
        ("layer", layer),
    ]
    if style_name:
        params.append(("style", style_name))
    return f"{base}?{urlencode(params)}"


def _iso_wms(value: datetime) -> str:
    """Return a compact UTC WMS timestamp."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _trim_times(values: list[datetime], spec: _LayerSpec, now: datetime) -> list[datetime]:
    """Bound very long provider timelines while preserving the useful current window."""
    if len(values) <= spec.max_frames:
        return values

    if spec.source_class == "observation":
        return values[-spec.max_frames :]

    nearest = min(range(len(values)), key=lambda index: abs((values[index] - now).total_seconds()))
    if spec.source_class == "forecast":
        start = max(0, nearest - 1)
        return values[start : start + spec.max_frames]

    past_slots = spec.max_frames // 2
    start = max(0, nearest - past_slots)
    end = min(len(values), start + spec.max_frames)
    start = max(0, end - spec.max_frames)
    return values[start:end]


def _default_index(values: list[datetime], spec: _LayerSpec, now: datetime) -> int:
    """Choose the initial frame: latest observation or nearest current valid time."""
    if not values:
        return -1
    if spec.source_class == "observation":
        return len(values) - 1

    not_future = [index for index, value in enumerate(values) if value <= now]
    if spec.source_class == "observation_forecast" and not_future:
        return not_future[-1]

    return min(range(len(values)), key=lambda index: abs((values[index] - now).total_seconds()))


def _frame_kind(value: datetime, spec: _LayerSpec, now: datetime) -> str:
    """Classify one timeline frame for generic Lab labelling."""
    if spec.source_class == "forecast":
        return "forecast"
    if spec.source_class == "observation":
        return "observation"
    return "observation" if value <= now else "forecast"


def _tile_url(base: str, layer: str, valid_time: datetime | None) -> str:
    """Build a MapLibre-compatible tiled WMS request URL."""
    params: list[tuple[str, str]] = [
        ("service", "WMS"),
        ("version", "1.1.1"),
        ("request", "GetMap"),
        ("layers", layer),
        ("styles", ""),
        ("format", "image/png"),
        ("transparent", "true"),
        ("srs", "EPSG:3857"),
        ("width", "256"),
        ("height", "256"),
        ("bbox", "{bbox-epsg-3857}"),
    ]
    if valid_time is not None:
        params.append(("time", _iso_wms(valid_time)))
    return f"{base}?{urlencode(params, safe='{}:,-')}"


class DwdProvider:
    """Official DWD WMS adapter for radar, satellite, nowcast and model layers."""

    id = "dwd"
    name = "Deutscher Wetterdienst (DWD)"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        """Return WeatherRouter map capabilities backed by official DWD WMS layers."""
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        """Return explanatory metadata for the generic provider info UI."""
        return ProviderInfo(
            summary=(
                "Der Deutsche Wetterdienst liefert WeatherRouter offizielle Radar-, "
                "Satelliten-, NowCastMIX- und ICON-Kartenprodukte über GeoServer/WMS."
            ),
            coverage="Deutschland und Europa, abhängig vom jeweiligen Produkt",
            strengths=(
                "offizielle deutsche Wetterdatenquelle",
                "Radar, Satellit, Warn-/Nowcast-nahe Produkte und Modellkarten",
                "mehrere fachlich unterschiedliche Kartenebenen in einem Provider",
            ),
            limitations=(
                "Abdeckung und Zeitschritte unterscheiden sich je Layer",
                "einzelne ereignisabhängige Layer können zeitweise keine aktuellen Frames besitzen",
            ),
            documentation_url="https://www.dwd.de/",
            attribution="Deutscher Wetterdienst (DWD)",
            services=(
                {"name": "Radar", "status": "integriert", "note": "Analyse/Vorhersage + RY"},
                {"name": "Meteosat", "status": "integriert", "note": "Wolken Tag/Nacht"},
                {"name": "NowCastMIX", "status": "integriert", "note": "Blitzdichte / Gewitterzellen"},
                {
                    "name": "DWD Warnungen",
                    "status": "integriert",
                    "note": "amtliche WarnWetter-Ereignisse als hazard_feed",
                },
                {"name": "ICON / ICON-EU", "status": "integriert", "note": "Modellkarten"},
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        """Return primary and backup DWD GeoServer destinations."""
        capability_ids = tuple(spec.capability_id for spec in _LAYER_SPECS)
        return (
            NetworkTargetInfo(
                purpose="wms_weather_layers",
                scheme="https",
                host="maps.dwd.de",
                port=443,
                target_type="wms",
                required=True,
                capabilities=capability_ids,
                note=(
                    "Offizieller DWD-GeoServer für Radar-, Satelliten-, Nowcast- und "
                    "ICON-Kartenebenen."
                ),
            ),
            NetworkTargetInfo(
                purpose="wms_weather_layers_backup",
                scheme="https",
                host="brz-maps.dwd.de",
                port=443,
                target_type="wms_backup",
                required=False,
                capabilities=capability_ids,
                note=(
                    "Dokumentiertes DWD-Ausfallsystem; WeatherRouter nutzt es für die "
                    "Descriptor-Ermittlung, wenn der Primärdienst nicht erreichbar ist."
                ),
            ),
            NetworkTargetInfo(
                purpose="official_weather_warnings",
                scheme="https",
                host="opendata.dwd.de",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=("official_weather_warnings",),
                note=(
                    "Amtlicher DWD CAP-Gemeindestatus mit Polygongeometrien und "
                    "WarnCellID für kontextbezogene Wetterwarnungen."
                ),
            ),
        )

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        """Return a one-shot, secret-free DWD WMS diagnostic snapshot."""
        if capability_id is not None and capability_id not in _CAPABILITY_MAP:
            return {
                "ok": False,
                "stage": "capability_selection",
                "error": {
                    "type": "ValueError",
                    "message": f"Unsupported DWD map capability: {capability_id}",
                },
            }

        attempts: list[dict[str, Any]] = []
        try:
            base, root = await _async_capabilities(hass, attempts)
        except Exception as err:  # noqa: BLE001 - explicit diagnostic capture
            cause = err.__cause__ or err.__context__
            return {
                "ok": False,
                "stage": "get_capabilities",
                "attempts": attempts,
                "error": {
                    "type": type(err).__name__,
                    "message": str(err),
                    "cause_type": type(cause).__name__ if cause else None,
                    "cause_message": str(cause) if cause else None,
                },
            }

        names = _named_layer_names(root)
        available = set(names)
        specs = (
            (_CAPABILITY_MAP[capability_id],)
            if capability_id is not None
            else _LAYER_SPECS
        )

        now = datetime.now(timezone.utc)
        layers: list[dict[str, Any]] = []
        for spec in specs:
            item: dict[str, Any] = {
                "capability": spec.capability_id,
                "display_name": spec.name,
                "expected_layer": spec.layer,
                "present": spec.layer in available,
                "source_class": spec.source_class,
            }
            if item["present"]:
                try:
                    raw_times, declared_default = _layer_time_dimension(root, spec.layer)
                    times = _trim_times(raw_times, spec, now)
                    item.update(
                        {
                            "time_dimension": {
                                "raw_count": len(raw_times),
                                "trimmed_count": len(times),
                                "first": _iso_wms(raw_times[0]) if raw_times else None,
                                "last": _iso_wms(raw_times[-1]) if raw_times else None,
                                "declared_default": declared_default,
                            },
                            "style_metadata": _layer_style_metadata(root, spec.layer),
                            "machine_coverage": await self.async_get_coverage(
                                hass,
                                spec.capability_id,
                            ),
                        }
                    )
                except Exception as err:  # noqa: BLE001 - report layer metadata issue
                    item["metadata_error"] = {
                        "type": type(err).__name__,
                        "message": str(err),
                    }
            layers.append(item)

        missing = [item["capability"] for item in layers if not item["present"]]
        return {
            "ok": not missing,
            "stage": "layer_discovery",
            "selected_endpoint": base,
            "cache": _capabilities_cache_diagnostic(),
            "attempts": attempts,
            "service": {
                "xml_root": _local_name(root.tag),
                "wms_version": root.attrib.get("version"),
                "named_layer_count": len(names),
            },
            "layers": layers,
            "missing_capabilities": missing,
            "available_layers": names,
        }

    def _start_coverage_lookup(
        self,
        hass: HomeAssistant,
        spec: _LayerSpec,
        *,
        refresh_if_aging: bool = False,
    ) -> asyncio.Task[dict[str, Any]]:
        """One finite task per verified WMS layer; isolate V2 cancellation."""
        loop = asyncio.get_running_loop()
        existing = _coverage_inflight.get(spec.layer)
        if existing is not None and not existing.done():
            return existing

        async def _resolve_and_cache() -> dict[str, Any]:
            try:
                result = await self._async_get_coverage_uncached(
                    hass, spec, refresh_if_aging=refresh_if_aging
                )
                loaded = monotonic()
                _coverage_result_cache[spec.layer] = {
                    "coverage": dict(result),
                    "loaded_at": loaded,
                    "valid_until": loaded + _CAPABILITIES_TTL_SECONDS,
                }
                _coverage_failure_retry_until.pop(spec.layer, None)
                _coverage_lookup_stage[spec.layer] = "verified"
                return result
            except Exception:
                _coverage_lookup_stage[spec.layer] = "failed"
                # A broken WMS host must not trigger a new 40s host-failover
                # operation on every map refresh. Never cache fake coverage.
                _coverage_failure_retry_until[spec.layer] = (
                    monotonic() + _COVERAGE_REFRESH_RETRY_SECONDS
                )
                raise

        task = loop.create_task(
            _resolve_and_cache(), name="wr-dwd-verified-layer-coverage"
        )
        task.add_done_callback(_observe_background_result)
        _coverage_inflight[spec.layer] = task
        return task

    async def async_get_coverage(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Use proven layer coverage while refreshing before its hard expiry.

        After first successful contact, ordinary map updates never wait for
        network renewal while the existing geographic proof is still valid.
        An expired proof is rejected until a new authoritative result arrives.
        """
        global _coverage_inflight_loop
        spec = _CAPABILITY_MAP.get(capability_id)
        if spec is None:
            raise ValueError(f"Unsupported DWD map capability: {capability_id}")

        loop = asyncio.get_running_loop()
        if _coverage_inflight_loop is not loop:
            _coverage_inflight_loop = loop
            _coverage_inflight.clear()
            _coverage_refresh_last_started.clear()
            _coverage_failure_retry_until.clear()
            _coverage_lookup_stage.clear()

        now = monotonic()
        cached = _cached_coverage_result(spec.layer, now)
        task = _coverage_inflight.get(spec.layer)
        if cached is not None:
            remaining = float(cached["cache"]["ttl_remaining_seconds"])
            if (
                remaining <= _COVERAGE_REFRESH_LEAD_SECONDS
                and (task is None or task.done())
                and now >= _coverage_refresh_last_started.get(spec.layer, 0.0)
                    + _COVERAGE_REFRESH_RETRY_SECONDS
            ):
                _coverage_refresh_last_started[spec.layer] = now
                self._start_coverage_lookup(
                    hass, spec, refresh_if_aging=True
                )
            return cached

        if task is None or task.done():
            if now < _coverage_failure_retry_until.get(spec.layer, 0.0):
                raise ValueError("DWD coverage provider temporarily unavailable")
            task = self._start_coverage_lookup(hass, spec)
        return dict(await asyncio.shield(task))

    def coverage_preflight_diagnostics(
        self, capability_id: str,
    ) -> dict[str, Any]:
        """Provider-neutral optional monitor detail: no network/URLs/coordinates."""
        spec = _CAPABILITY_MAP.get(capability_id)
        if spec is None:
            return {}
        now = monotonic()
        cached = _coverage_result_cache.get(spec.layer)
        task = _coverage_inflight.get(spec.layer)
        remaining = (
            float(cached.get("valid_until", 0.0)) - now
            if isinstance(cached, dict) else None
        )
        return {
            "cache_valid": remaining is not None and remaining > 0,
            "cache_ttl_remaining_seconds": (
                round(max(0.0, remaining), 2) if remaining is not None else None
            ),
            "refresh_running": task is not None and not task.done(),
            "lookup_stage": (
                _coverage_lookup_stage.get(spec.layer)
                if task is not None and not task.done() else None
            ),
            "aggregate_wms_cached": (
                _cached_root is not None and now < _cache_valid_until
            ),
            "global_wms_refresh_running": any(
                not value.done() for value in _global_wms_inflight.values()
            ),
            "retry_after_seconds": round(max(
                0.0, _coverage_failure_retry_until.get(spec.layer, 0.0) - now
            ), 2),
        }

    async def _async_get_coverage_uncached(
        self,
        hass: HomeAssistant,
        spec: _LayerSpec,
        *,
        refresh_if_aging: bool = False,
    ) -> dict[str, Any]:
        """Existing WMS layer and fallback validation, unchanged."""
        _coverage_lookup_stage[spec.layer] = "aggregate_wms"
        cache_before = _capabilities_cache_diagnostic()
        base, root = await _async_capabilities(
            hass, refresh_if_aging=refresh_if_aging
        )
        _coverage_lookup_stage[spec.layer] = "aggregate_layer_bbox"
        coverage = await _wms_layer_coverage(hass, root, spec.layer)
        if coverage is None:
            attempts: list[dict[str, Any]] = []
            _coverage_lookup_stage[spec.layer] = "global_wms"
            try:
                return await _async_global_wms_coverage(
                    hass,
                    spec.layer,
                    attempts=attempts,
                    refresh_if_aging=refresh_if_aging,
                )
            except Exception as global_err:  # noqa: BLE001 - explicit fallback chain
                _coverage_lookup_stage[spec.layer] = "layer_specific_wms"
                try:
                    return await _async_layer_specific_coverage(
                        hass,
                        spec.layer,
                        preferred_base=base,
                        attempts=attempts,
                        refresh_if_aging=refresh_if_aging,
                    )
                except Exception as layer_err:  # noqa: BLE001 - preserve hard coverage
                    documented_grid = _documented_icon_global_grid_coverage(
                        spec.layer,
                        attempts,
                    )
                    if documented_grid is not None:
                        return documented_grid

                    stages = []
                    for item in attempts:
                        stage = str(item.get("stage") or "unknown")
                        status = item.get("http_status")
                        present = item.get("target_present")
                        message = str(item.get("message") or "")
                        detail = stage
                        if status is not None:
                            detail += f"/http={status}"
                        if present is not None:
                            detail += f"/target_present={present}"
                        if message:
                            detail += f"/{message[:160]}"
                        stages.append(detail)
                    summary = "; ".join(stages) or "no fallback diagnostics"
                    raise ValueError(
                        "DWD machine-readable WMS coverage is unavailable for "
                        f"{spec.layer}; fallbacks: {summary}"
                    ) from layer_err

        result = dict(coverage)
        result["endpoint_host"] = urlsplit(base).hostname
        result["coverage_metadata_scope"] = "aggregate_wms"
        result["aggregate_coverage_missing"] = False
        cache_after = _capabilities_cache_diagnostic()
        cache_after["hit"] = bool(cache_before.get("valid"))
        result["cache"] = cache_after
        return result

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Return one DWD WMS layer as a generic MapLibre raster descriptor."""
        spec = _CAPABILITY_MAP.get(capability_id)
        if spec is None:
            raise ValueError(f"Unsupported DWD map capability: {capability_id}")

        base, root = await _async_capabilities(hass)
        raw_times, declared_default = _layer_time_dimension(root, spec.layer)
        style_metadata = _layer_style_metadata(root, spec.layer)
        now = datetime.now(timezone.utc)
        times = _trim_times(raw_times, spec, now)
        default_index = _default_index(times, spec, now)

        frames = [
            {
                "time": int(value.timestamp()),
                "tile_url": _tile_url(base, spec.layer, value),
                "kind": _frame_kind(value, spec, now),
            }
            for value in times
        ]

        if frames and default_index >= 0:
            selected = frames[default_index]
            tile_url = selected["tile_url"]
            frame_time: int | None = selected["time"]
        else:
            tile_url = _tile_url(base, spec.layer, None)
            frame_time = None

        host = urlsplit(base).hostname
        layer: dict[str, Any] = {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _DWD_PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": spec.source_class,
            "render_mode": "raster_tile",
            "frame_time": frame_time,
            "tile_url": tile_url,
            "tile_size": 256,
            "max_zoom": spec.max_zoom,
            "default_opacity": spec.default_opacity,
            "attribution": (
                'Daten: <a href="https://www.dwd.de/" target="_blank" '
                'rel="noopener noreferrer">Deutscher Wetterdienst (DWD)</a>'
            ),
            "network_hosts": [host] if host else [],
            "provider_metadata": {
                "service": "WMS",
                "layer": spec.layer,
                "capabilities_default": declared_default,
                "selected_host": host,
                "default_style": style_metadata.get("default_style"),
                "styles": style_metadata.get("styles", []),
            },
            "legend": {
                "title": spec.name,
                "url": (
                    style_metadata.get("legend_url")
                    or _legend_url(base, spec.layer, style_metadata.get("default_style"))
                ),
                "style": style_metadata.get("default_style"),
            },
        }

        if frames:
            layer["timeline"] = {
                "mode": "frames",
                "default": "current",
                "default_index": default_index,
                "current_index": default_index,
                "loop": True,
                "frames": frames,
            }

        return layer

    async def async_get_hazard_feed(
        self,
        hass: HomeAssistant,
        capability_id: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 250,
    ) -> dict[str, Any]:
        """Return active official DWD CAP warnings with real spatial evidence."""
        if capability_id != "official_weather_warnings":
            raise ValueError(f"Unsupported DWD hazard capability: {capability_id}")

        session = async_get_clientsession(hass)
        async with session.get(
            _DWD_CAP_WARNINGS_URL,
            headers={
                "Accept": "application/zip,application/octet-stream,*/*",
                "User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev)",
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            response.raise_for_status()
            raw_payload = await response.read()

        parsed = await hass.async_add_executor_job(_parse_dwd_cap_zip, raw_payload)
        raw_events = [
            item for item in parsed.get("events", [])
            if isinstance(item, dict)
        ]
        filtered_events, spatial_filter = _filter_dwd_cap_events(
            raw_events,
            latitude=latitude,
            longitude=longitude,
            bbox=bbox,
        )
        maximum = max(1, min(int(limit), 1000))
        events = filtered_events[:maximum]

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _DWD_PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "warning",
            "source_semantics": "warning_authority",
            "render_mode": "hazard_feed",
            "coverage_status": (
                "context_match"
                if (
                    spatial_filter["mode"] in {"point", "bbox"}
                    and spatial_filter["matched_event_count"] > 0
                )
                else "unknown"
                if spatial_filter["mode"] in {"point", "bbox"}
                else "regional"
            ),
            "events": events,
            "event_count": len(events),
            "unfiltered_event_count": len(raw_events),
            "attribution": "Deutscher Wetterdienst (DWD)",
            "geometry_status": (
                "cap_polygon"
                if parsed.get("geometry_event_count", 0)
                else "no_active_geometry"
            ),
            "spatial_filter": spatial_filter,
            "provider_metadata": {
                "service": "CAP",
                "product": "COMMUNEUNION_CELLS_STAT",
                "zip_member_count": parsed.get("zip_member_count"),
                "parsed_alert_count": parsed.get("parsed_alert_count"),
                "invalid_xml_count": parsed.get("invalid_xml_count"),
                "geometry_event_count": parsed.get("geometry_event_count"),
                "endpoint_host": "opendata.dwd.de",
            },
        }

