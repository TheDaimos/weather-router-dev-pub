"""Smithsonian / USGS Global Volcanism Program weekly activity provider."""

from __future__ import annotations

from email.utils import parsedate_to_datetime
from html import unescape
from math import isfinite
import re
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import volcano_semantics

_PROVIDER_REVISION = "wr-0.10.132-gvp-http-identification-1"
_RSS_URL = "https://volcano.si.edu/news/WeeklyVolcanoRSS.xml"
_TAG_RE = re.compile(r"<[^>]+>")

_CAPABILITIES = (
    CapabilityInfo(
        id="weekly_volcanic_activity",
        name="Vulkanaktivität weltweit · GVP Wochenbericht",
        unit=None,
        source_class="observation",
        render_mode="hazard_feed",
        description=(
            "Smithsonian/USGS Weekly Volcanic Activity Report mit GeoRSS-Positionen "
            "für weltweit berichtete Vulkanaktivität."
        ),
        coverage="Global",
        temporal_resolution="Wochenbericht",
        strengths=(
            "weltweite Smithsonian Global Volcanism Program Quelle",
            "GeoRSS-Koordinaten für kartierbare Vulkane",
            "neue/unruhige und fortlaufende Aktivität werden quellengetreu benannt",
        ),
        limitations=(
            "Wochenbericht, kein Echtzeit-Warnfeed",
            "der Weekly Volcanic Activity Report ist ausdrücklich keine vollständige "
            "Liste aller weltweiten Eruptionen",
            "amtliche lokale Warnstufen müssen weiterhin bei den zuständigen Observatorien "
            "geprüft werden",
        ),
        documentation_url="https://volcano.si.edu/reports_weekly.cfm",
    ),
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag) == name:
            value = (child.text or "").strip()
            return value or None
    return None


def _children_text(element: ET.Element, name: str) -> list[str]:
    result: list[str] = []
    for child in element:
        if _local_name(child.tag) != name:
            continue
        value = (child.text or "").strip()
        if value:
            result.append(value)
    return result


def _clean_html(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = unescape(_TAG_RE.sub(" ", value))
    cleaned = " ".join(cleaned.split())
    return cleaned[:8000] or None


def _rss_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, OverflowError):
        return value


def _safe_gvp_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or parsed.hostname not in {
        "volcano.si.edu",
        "www.volcano.si.edu",
    }:
        return None
    if parsed.scheme == "http":
        return value.replace("http://", "https://", 1)
    return value


def _geo_point(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    bits = value.replace(",", " ").split()
    if len(bits) < 2:
        return None
    try:
        latitude = float(bits[0])
        longitude = float(bits[1])
    except ValueError:
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


def _report_kind(title: str) -> str | None:
    if " - " not in title:
        return None
    tail = title.rsplit(" - ", 1)[-1].strip()
    return tail or None


def _volcano_name(title: str) -> str:
    for marker in (" - Report for ", " — Report for "):
        if marker in title:
            return title.split(marker, 1)[0].strip()
    return title.split(" - ", 1)[0].strip() or title


def _parse_rss(payload: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    events: list[dict[str, Any]] = []

    for item in root.iter():
        if _local_name(item.tag) != "item":
            continue
        title = _child_text(item, "title") or "Vulkanaktivität · GVP"
        description = _clean_html(_child_text(item, "description"))
        link = _safe_gvp_url(_child_text(item, "link"))
        published = _rss_time(_child_text(item, "pubDate"))
        point = _geo_point(_child_text(item, "point"))
        categories = _children_text(item, "category")
        volcano = _volcano_name(title)
        kind = _report_kind(title)

        events.append(
            {
                "id": link or f"gvp:{published or 'current'}:{volcano}",
                "hazard_type": "volcanic_activity",
                "volcano_semantics": volcano_semantics(
                    "weekly_volcanic_activity_report_event",
                    report_type=kind,
                    report_categories=categories,
                ),
                "event": kind or "Weekly Volcanic Activity Report",
                "headline": title,
                "severity": "unknown",
                "urgency": "unknown",
                "certainty": "observed",
                "status": "actual",
                "message_type": "report",
                "sent": published,
                "effective": published,
                "onset": None,
                "expires": None,
                "ends": None,
                "area_desc": volcano,
                "geometry": point,
                "description": description,
                "instruction": None,
                "sender_name": "Smithsonian Global Volcanism Program / USGS",
                "response": "monitor",
                "affected_zones": [],
                "parameters": {
                    "report_type": kind,
                    "categories": categories,
                    "weekly_report": True,
                    "severity_basis": "not_assigned_by_source",
                },
                "web_url": link,
            }
        )
    return events


class SmithsonianVolcanoProvider:
    """Expose the GVP Weekly Volcanic Activity Report as a hazard feed."""

    id = "smithsonian_volcanoes"
    name = "Smithsonian / USGS · Vulkane weltweit"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Das Smithsonian Global Volcanism Program veröffentlicht gemeinsam mit "
                "USGS den Weekly Volcanic Activity Report für weltweit berichtete "
                "Vulkanaktivität."
            ),
            coverage="Global",
            strengths=(
                "weltweiter Überblick",
                "GeoRSS-Punkte für die Kartenansicht",
                "direkter Link zum jeweiligen GVP-Bericht",
            ),
            limitations=(
                "kein Echtzeit-Warndienst",
                "Wochenbericht ist nicht vollständig für jede laufende Eruption",
                "lokale Observatorien und Behörden bleiben für Warnungen maßgeblich",
            ),
            documentation_url="https://volcano.si.edu/reports_weekly.cfm",
            attribution="Smithsonian Institution · Global Volcanism Program / USGS",
            services=(
                {
                    "name": "Weekly Volcanic Activity Report · GeoRSS",
                    "status": "integriert",
                    "note": "weltweit berichtete Aktivität, wöchentlicher Veröffentlichungsrhythmus",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="global_weekly_volcanic_activity",
                scheme="https",
                host="volcano.si.edu",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=("weekly_volcanic_activity",),
                note="Smithsonian / USGS Weekly Volcanic Activity Report RSS/GeoRSS.",
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
        if capability_id != "weekly_volcanic_activity":
            raise ValueError(f"Unsupported Smithsonian volcano capability: {capability_id}")

        session = async_get_clientsession(hass)
        async with session.get(
            _RSS_URL,
            headers={
                "Accept": "application/rss+xml,application/xml,text/xml,*/*",
                "User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)",
            },
            timeout=20,
        ) as response:
            response.raise_for_status()
            payload = await response.read()

        events = [
            item for item in _parse_rss(payload)
            if _point_in_bbox(item.get("geometry"), bbox)
        ]
        maximum = max(1, min(int(limit), 1000))
        events = events[:maximum]

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "observation",
            "render_mode": "hazard_feed",
            "coverage_status": "viewport_filtered" if bbox is not None else "global",
            "events": events,
            "event_count": len(events),
            "provider_metadata": {
                "weekly_report": True,
                "real_time_warning_feed": False,
                "bbox_filtered": bbox is not None,
                "geocoded_event_count": sum(
                    1 for item in events if isinstance(item.get("geometry"), dict)
                ),
            },
            "attribution": "Smithsonian Institution · Global Volcanism Program / USGS",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id not in {None, "weekly_volcanic_activity"}:
            return {
                "ok": False,
                "stage": "capability_selection",
                "provider_revision": _PROVIDER_REVISION,
            }
        feed = await self.async_get_hazard_feed(
            hass,
            "weekly_volcanic_activity",
            limit=50,
        )
        return {
            "ok": True,
            "stage": "gvp_weekly_rss_georss",
            "provider_revision": _PROVIDER_REVISION,
            "event_count": feed.get("event_count", 0),
            "geocoded_event_count": (feed.get("provider_metadata") or {}).get(
                "geocoded_event_count",
                0,
            ),
            "sample": [
                {
                    "headline": item.get("headline"),
                    "report_type": (item.get("parameters") or {}).get("report_type"),
                    "has_geometry": isinstance(item.get("geometry"), dict),
                    "sent": item.get("sent"),
                }
                for item in feed.get("events", [])[:5]
            ],
        }
