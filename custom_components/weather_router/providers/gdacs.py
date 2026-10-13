"""GDACS global disaster-awareness hazard provider."""

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
from .hazard_common import earthquake_semantics, geometry_intersects_bbox, tsunami_semantics, volcano_semantics

_PROVIDER_REVISION = "wr-0.10.131-volcano-semantics-1"
_RSS_URL = "https://data.gdacs.org/xml/rss_7d.xml"
_TAG_RE = re.compile(r"<[^>]+>")

_CAPABILITY_ID = "global_disaster_alerts_7d"
_CAPABILITIES = (
    CapabilityInfo(
        id=_CAPABILITY_ID,
        name="Globale Katastrophenlage · GDACS · letzte 7 Tage",
        unit=None,
        source_class="disaster_awareness",
        render_mode="hazard_feed",
        description=(
            "GDACS-Ereignisse der letzten sieben Tage für Erdbeben, tropische "
            "Wirbelstürme, Hochwasser, Vulkane, Waldbrände, Tsunamis und Dürren."
        ),
        coverage="Global",
        temporal_resolution="Feed-Aktualisierung typischerweise alle 6 Minuten",
        strengths=(
            "UN-/EU-Kooperationssystem für globale Katastrophenlage",
            "einheitliche Alert-Level und GeoRSS-Koordinaten",
            "guter globaler Zweitblick neben fachlich zuständigen Primärquellen",
        ),
        limitations=(
            "aggregierter Awareness-Dienst, nicht für jede Gefahr die zuständige Primärwarnstelle",
            "GDACS-Alert-Level darf nicht als lokale behördliche Warnstufe umgedeutet werden",
            "Ereignisse können sich mit spezialisierten WeatherRouter-Providern überschneiden",
        ),
        documentation_url="https://data.gdacs.org/feed_reference.aspx",
    ),
)

_TYPE_MAP = {
    "EQ": "earthquake",
    "TC": "tropical_cyclone",
    "FL": "flood",
    "VO": "volcanic_activity",
    "WF": "wildfire",
    "TS": "tsunami",
    "DR": "drought",
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str | None:
    for child in element:
        if _local_name(child.tag).casefold() == name.casefold():
            value = (child.text or "").strip()
            return value or None
    return None


def _clean_text(value: str | None, *, maximum: int = 8000) -> str | None:
    if not value:
        return None
    value = unescape(_TAG_RE.sub(" ", value))
    value = " ".join(value.split()).strip()
    return value[:maximum] or None


def _rss_time(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, OverflowError):
        return value


def _safe_gdacs_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.hostname not in {"gdacs.org", "www.gdacs.org", "data.gdacs.org"}:
        return None
    if parsed.scheme == "http":
        return value.replace("http://", "https://", 1)
    return value if parsed.scheme == "https" else None


def _point(item: ET.Element) -> dict[str, Any] | None:
    lat = _child_text(item, "lat")
    lon = _child_text(item, "long")
    if lat is None or lon is None:
        point = _child_text(item, "point")
        if point:
            bits = point.replace(",", " ").split()
            if len(bits) >= 2:
                lat, lon = bits[0], bits[1]
    try:
        latitude = float(lat) if lat is not None else None
        longitude = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        return None
    if (
        latitude is None
        or longitude is None
        or not isfinite(latitude)
        or not isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        return None
    return {"type": "Point", "coordinates": [longitude, latitude]}


def _severity(alert_level: str | None) -> str:
    return {
        "green": "minor",
        "orange": "severe",
        "red": "extreme",
    }.get(str(alert_level or "").casefold(), "unknown")


def _parse_rss(payload: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    events: list[dict[str, Any]] = []

    for item in root.iter():
        if _local_name(item.tag) != "item":
            continue
        event_type_short = str(_child_text(item, "eventtype") or "").upper()
        hazard_type = _TYPE_MAP.get(event_type_short, "natural_hazard")
        alert_level = _child_text(item, "alertlevel")
        title = _clean_text(_child_text(item, "title"), maximum=1000) or "GDACS-Ereignis"
        description = _clean_text(_child_text(item, "description"))
        event_id = _child_text(item, "eventid")
        guid = _child_text(item, "guid")
        country = _child_text(item, "country")
        link = _safe_gdacs_url(_child_text(item, "link"))
        published = _rss_time(_child_text(item, "pubDate"))
        from_date = _rss_time(_child_text(item, "fromdate"))
        to_date = _rss_time(_child_text(item, "todate"))
        geometry = _point(item)

        events.append(
            {
                "id": f"gdacs:{event_type_short}:{event_id or guid or title}",
                "hazard_type": hazard_type,
                "earthquake_semantics": (
                    earthquake_semantics("disaster_awareness_earthquake_event")
                    if hazard_type == "earthquake"
                    else None
                ),
                "volcano_semantics": (
                    volcano_semantics("disaster_awareness_volcanic_event")
                    if hazard_type == "volcanic_activity"
                    else None
                ),
                "tsunami_semantics": (
                    tsunami_semantics("disaster_awareness_tsunami_event", wave_evidence="none")
                    if hazard_type == "tsunami"
                    else None
                ),
                "tropical_system": (
                    {
                        "system_class": "tropical_cyclone_unspecified",
                        "source_classification": "GDACS TC",
                        "classification_source": "explicit_event_text",
                    }
                    if hazard_type == "tropical_cyclone"
                    else None
                ),
                "event": f"GDACS {event_type_short or 'event'}",
                "headline": title,
                "severity": _severity(alert_level),
                "urgency": "unknown",
                "certainty": "observed",
                "status": "actual",
                "message_type": "alert",
                "sent": published,
                "effective": from_date or published,
                "onset": from_date,
                "expires": to_date,
                "ends": to_date,
                "area_desc": country,
                "geometry": geometry,
                "description": description,
                "instruction": None,
                "sender_name": "Global Disaster Alert and Coordination System (GDACS)",
                "response": "monitor",
                "affected_zones": [],
                "source_semantics": "disaster_awareness_alert",
                "parameters": {
                    "gdacs_event_type": event_type_short,
                    "gdacs_alert_level": alert_level,
                    "gdacs_alert_score": _child_text(item, "alertscore"),
                    "gdacs_episode_alert_level": _child_text(item, "episodealertlevel"),
                    "gdacs_event_id": event_id,
                    "gdacs_episode_id": _child_text(item, "episodeid"),
                    "gdacs_country": country,
                    "gdacs_severity_text": _child_text(item, "severity"),
                    "gdacs_population": _child_text(item, "population"),
                    "gdacs_is_current": _child_text(item, "iscurrent"),
                },
                "web_url": link,
            }
        )

    return events


class GdacsProvider:
    """Expose the GDACS seven-day public disaster-awareness feed."""

    id = "gdacs"
    name = "GDACS · Globale Katastrophenlage"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "GDACS ist ein Kooperationssystem der Vereinten Nationen, Europäischen "
                "Kommission und Katastrophenschutzakteure für frühe globale Lageübersicht "
                "bei größeren plötzlich eintretenden Katastrophen."
            ),
            coverage="Global",
            strengths=(
                "mehrere Naturgefahren in einem einheitlichen Feed",
                "GeoRSS-Positionen und GDACS-Alert-Level",
                "öffentliche, dokumentierte Feeds",
            ),
            limitations=(
                "kein Ersatz für die jeweils zuständige nationale oder fachliche Warnstelle",
                "Überschneidungen mit spezialisierten WeatherRouter-Quellen sind beabsichtigt",
            ),
            documentation_url="https://data.gdacs.org/feed_reference.aspx",
            attribution="Global Disaster Alert and Coordination System (GDACS)",
            services=(
                {
                    "name": "GDACS RSS · letzte 7 Tage",
                    "status": "integriert",
                    "note": "öffentlicher Feed; expliziter Abruf",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="global_disaster_awareness",
                scheme="https",
                host="data.gdacs.org",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=(_CAPABILITY_ID,),
                note="GDACS öffentlicher Sieben-Tage-RSS/GeoRSS-Feed.",
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
        if capability_id != _CAPABILITY_ID:
            raise ValueError(f"Unsupported GDACS capability: {capability_id}")

        session = async_get_clientsession(hass)
        async with session.get(
            _RSS_URL,
            headers={
                "Accept": "application/rss+xml,application/xml,text/xml,*/*",
                "User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)",
            },
            timeout=25,
        ) as response:
            response.raise_for_status()
            payload = await response.read()

        # Tsunami geometry is evaluated centrally so non-matches remain diagnosable.
        events = [
            event for event in _parse_rss(payload)
            if event.get("hazard_type") == "tsunami"
            or geometry_intersects_bbox(event.get("geometry"), bbox)
        ]
        maximum = max(1, min(int(limit), 1000))
        events = events[:maximum]

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "disaster_awareness",
            "render_mode": "hazard_feed",
            "coverage_status": "viewport_filtered" if bbox is not None else "global",
            "events": events,
            "event_count": len(events),
            "provider_metadata": {
                "aggregator": True,
                "primary_warning_authority": False,
                "feed_window": "7d",
                "bbox_filtered": bbox is not None,
            },
            "attribution": "Global Disaster Alert and Coordination System (GDACS)",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id not in {None, _CAPABILITY_ID}:
            return {"ok": False, "stage": "capability_selection"}
        feed = await self.async_get_hazard_feed(hass, _CAPABILITY_ID, limit=50)
        return {
            "ok": True,
            "stage": "gdacs_rss_7d",
            "provider_revision": _PROVIDER_REVISION,
            "event_count": feed.get("event_count", 0),
            "hazard_types": sorted(
                {
                    item.get("hazard_type")
                    for item in feed.get("events", [])
                    if item.get("hazard_type")
                }
            ),
            "sample": [
                {
                    "headline": item.get("headline"),
                    "hazard_type": item.get("hazard_type"),
                    "severity": item.get("severity"),
                    "has_geometry": isinstance(item.get("geometry"), dict),
                }
                for item in feed.get("events", [])[:5]
            ],
        }
