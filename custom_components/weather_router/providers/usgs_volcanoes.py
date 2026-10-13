"""USGS Volcano Hazards Program elevated-status HANS provider."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import volcano_semantics

_PROVIDER_REVISION = "wr-0.10.131-volcano-semantics-1"
_ELEVATED_URL = "https://volcanoes.usgs.gov/hans-public/api/volcano/getElevatedVolcanoes"
_CATALOG_URL = "https://volcanoes.usgs.gov/hans-public/api/volcano/getUSVolcanoes"

_CAPABILITIES = (
    CapabilityInfo(
        id="elevated_us_volcanoes",
        name="Erhöhte Vulkanaktivität · USGS",
        unit=None,
        source_class="warning",
        render_mode="hazard_feed",
        description=(
            "USGS-HANS-Vulkane mit erhöhter Aviation Color Code- und/oder "
            "Volcano Alert Level-Einstufung."
        ),
        coverage="USA und von USGS-Observatorien überwachte US-Gebiete",
        temporal_resolution="status-/notice-gesteuert",
        strengths=(
            "offizieller USGS Volcano Hazards Program Status",
            "Aviation Color Code und Volcano Alert Level bleiben getrennt erhalten",
            "Koordinaten werden aus dem offiziellen USGS-Vulkankatalog ergänzt",
        ),
        limitations=(
            "nur USGS-Zuständigkeitsbereich, kein globaler Vulkanwarnfeed",
            "Statusstufen beschreiben vulkanische Unruhe/Aktivität und sind keine "
            "direkte Schadensprognose",
        ),
        documentation_url="https://volcanoes.usgs.gov/hans-public/api/volcano/",
    ),
)


def _iso_from_seconds(value: Any) -> str | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(seconds):
        return None
    return (
        datetime.fromtimestamp(seconds, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _safe_usgs_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {
        "volcanoes.usgs.gov",
        "www.usgs.gov",
        "usgs.gov",
    }:
        return None
    return value


def _severity(color_code: Any, alert_level: Any) -> str:
    color = str(color_code or "").upper()
    alert = str(alert_level or "").upper()
    if color == "RED" or alert == "WARNING":
        return "extreme"
    if color == "ORANGE" or alert == "WATCH":
        return "severe"
    if color == "YELLOW" or alert == "ADVISORY":
        return "moderate"
    return "unknown"


def _point(catalog_item: Any) -> dict[str, Any] | None:
    if not isinstance(catalog_item, dict):
        return None
    try:
        latitude = float(catalog_item.get("latitude"))
        longitude = float(catalog_item.get("longitude"))
    except (TypeError, ValueError):
        return None
    if not (
        isfinite(latitude)
        and isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        return None
    return {"type": "Point", "coordinates": [longitude, latitude]}


def _point_in_bbox(
    geometry: dict[str, Any] | None,
    bbox: tuple[float, float, float, float] | None,
) -> bool:
    if bbox is None or geometry is None:
        return True
    longitude, latitude = geometry["coordinates"][:2]
    west, south, east, north = bbox
    longitude_ok = west <= longitude <= east if west <= east else (
        longitude >= west or longitude <= east
    )
    return longitude_ok and south <= latitude <= north


def _catalog_map(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        vnum = str(item.get("vnum") or "")
        if vnum:
            result[vnum] = item
    return result


class UsgsVolcanoProvider:
    """Expose USGS HANS elevated volcano statuses through hazard_feed."""

    id = "usgs_volcanoes"
    name = "USGS · Vulkanstatus"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Das USGS Volcano Hazards Program veröffentlicht über HANS Vulkane "
                "mit erhöhter Aviation Color Code- bzw. Volcano Alert Level-Einstufung."
            ),
            coverage="USA und von USGS-Observatorien betreute US-Gebiete",
            strengths=(
                "offizielle USGS-HANS-Statusmeldungen",
                "YELLOW/ORANGE/RED und ADVISORY/WATCH/WARNING",
                "Verknüpfung mit offiziellen USGS-Vulkankoordinaten",
            ),
            limitations=(
                "regionaler USGS-Dienst und deshalb nicht weltweit vollständig",
                "für globale Aktivität ergänzt WeatherRouter separat Smithsonian/GVP",
            ),
            documentation_url="https://volcanoes.usgs.gov/hans-public/api/volcano/",
            attribution="U.S. Geological Survey · Volcano Hazards Program",
            services=(
                {
                    "name": "HANS Elevated Volcanoes",
                    "status": "integriert",
                    "note": "aktuell erhöhte USGS-Vulkanstatus",
                },
                {
                    "name": "HANS U.S. Volcano Catalog",
                    "status": "integriert",
                    "note": "Koordinaten- und Stammdatenauflösung",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="elevated_volcano_status",
                scheme="https",
                host="volcanoes.usgs.gov",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=("elevated_us_volcanoes",),
                note="USGS HANS elevated-volcano status and U.S. volcano catalog.",
            ),
        )

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
        del latitude, longitude
        if capability_id != "elevated_us_volcanoes":
            raise ValueError(f"Unsupported USGS volcano capability: {capability_id}")

        session = async_get_clientsession(hass)
        async with session.get(
            _ELEVATED_URL,
            headers={"Accept": "application/json"},
            timeout=20,
        ) as response:
            response.raise_for_status()
            elevated = await response.json(content_type=None)
        async with session.get(
            _CATALOG_URL,
            headers={"Accept": "application/json"},
            timeout=20,
        ) as response:
            response.raise_for_status()
            catalog_payload = await response.json(content_type=None)

        if not isinstance(elevated, list):
            raise ValueError("USGS elevated-volcano response is not a list")
        catalog = _catalog_map(catalog_payload)
        events: list[dict[str, Any]] = []

        for item in elevated:
            if not isinstance(item, dict):
                continue
            vnum = str(item.get("vnum") or "")
            volcano = catalog.get(vnum, {})
            geometry = _point(volcano)
            if not _point_in_bbox(geometry, bbox):
                continue

            color_code = str(item.get("color_code") or "UNASSIGNED").upper()
            alert_level = str(item.get("alert_level") or "UNASSIGNED").upper()
            sent = _iso_from_seconds(item.get("sent_unixtime"))
            name = str(item.get("volcano_name") or volcano.get("volcano_name") or vnum or "Vulkan")
            observatory = str(item.get("obs_fullname") or volcano.get("obs_fullname") or "USGS Volcano Observatory")
            notice_url = _safe_usgs_url(item.get("notice_url"))
            severity = _severity(color_code, alert_level)

            events.append(
                {
                    "id": f"{item.get('notice_identifier') or 'usgs-volcano'}:{vnum or name}",
                    "hazard_type": "volcanic_activity",
                    "volcano_semantics": volcano_semantics(
                        "official_volcano_status_event",
                        aviation_color_code=color_code,
                        volcano_alert_level=alert_level,
                        smithsonian_vnum=vnum or None,
                        volcano_code=volcano.get("volcano_cd"),
                        observatory=observatory,
                        region=volcano.get("region"),
                        nvews_threat=volcano.get("nvews_threat"),
                        notice_type=item.get("notice_type_cd"),
                        legacy_severity_band=severity,
                    ),
                    "event": "Elevated Volcano Status",
                    "headline": f"{name} · {color_code} / {alert_level}",
                    "severity": severity,
                    "urgency": "expected",
                    "certainty": "observed",
                    "status": "actual",
                    "message_type": "status",
                    "sent": sent,
                    "effective": sent,
                    "onset": None,
                    "expires": None,
                    "ends": None,
                    "area_desc": str(volcano.get("region") or name),
                    "geometry": geometry,
                    "description": (
                        f"{name}: Aviation Color Code {color_code}, "
                        f"Volcano Alert Level {alert_level}."
                    ),
                    "instruction": None,
                    "sender_name": observatory,
                    "response": "monitor",
                    "affected_zones": [],
                    "parameters": {
                        "alert_level": alert_level.casefold(),
                        "aviation_color_code": color_code,
                        "volcano_alert_level": alert_level,
                        "smithsonian_vnum": vnum or None,
                        "volcano_code": volcano.get("volcano_cd"),
                        "observatory": observatory,
                        "region": volcano.get("region"),
                        "elevation_meters": volcano.get("elevation_meters"),
                        "nvews_threat": volcano.get("nvews_threat"),
                        "notice_type": item.get("notice_type_cd"),
                    },
                    "web_url": notice_url or _safe_usgs_url(volcano.get("volcano_url")),
                }
            )

        events.sort(key=lambda value: str(value.get("sent") or ""), reverse=True)
        maximum = max(1, min(int(limit), 1000))
        events = events[:maximum]

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "warning",
            "render_mode": "hazard_feed",
            "coverage_status": "viewport_filtered" if bbox is not None else "regional",
            "events": events,
            "event_count": len(events),
            "provider_metadata": {
                "elevated_source_count": len(elevated),
                "catalog_count": len(catalog),
                "bbox_filtered": bbox is not None,
                "status_semantics": "USGS Aviation Color Code + Volcano Alert Level",
            },
            "attribution": "U.S. Geological Survey · Volcano Hazards Program",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id not in {None, "elevated_us_volcanoes"}:
            return {
                "ok": False,
                "stage": "capability_selection",
                "provider_revision": _PROVIDER_REVISION,
            }
        feed = await self.async_get_hazard_feed(
            hass,
            "elevated_us_volcanoes",
            limit=50,
        )
        return {
            "ok": True,
            "stage": "usgs_hans_elevated_plus_catalog",
            "provider_revision": _PROVIDER_REVISION,
            "event_count": feed.get("event_count", 0),
            "sample": [
                {
                    "headline": item.get("headline"),
                    "severity": item.get("severity"),
                    "alert_level": (item.get("parameters") or {}).get("volcano_alert_level"),
                    "aviation_color_code": (item.get("parameters") or {}).get("aviation_color_code"),
                    "has_geometry": isinstance(item.get("geometry"), dict),
                }
                for item in feed.get("events", [])[:5]
            ],
        }
