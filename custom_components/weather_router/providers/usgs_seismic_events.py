"""USGS observed non-earthquake seismic event provider."""

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
_FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
_CAPABILITY_ID = "non_earthquake_seismic_past_day"

_CAPABILITIES = (
    CapabilityInfo(
        id=_CAPABILITY_ID,
        name="Seismische Nicht-Erdbeben-Ereignisse · USGS · 24 h",
        unit=None,
        source_class="observation",
        render_mode="hazard_feed",
        description=(
            "USGS-ComCat-Ereignisse des Tages, deren Quelltyp ausdrücklich nicht "
            "'earthquake' ist, zum Beispiel Quarry Blast, Explosion, Kollaps oder Meteor."
        ),
        coverage="Global soweit durch USGS/ANSS katalogisiert",
        temporal_resolution="laufend aktualisierter 24-h-Feed",
        strengths=(
            "Quelltyp wird unverändert aus USGS ComCat erhalten",
            "Koordinate, Magnitude und Tiefe soweit vorhanden",
            "keine automatische Deutung einer Explosion als Anschlag oder Ursache",
        ),
        limitations=(
            "kein weltweiter Explosionsdetektor und keine Garantie, dass jedes Ereignis erfasst wird",
            "USGS-Ereignistyp beschreibt die seismische Katalogklassifikation",
            "WeatherRouter leitet daraus keine politische, militärische oder strafrechtliche Ursache ab",
        ),
        documentation_url="https://earthquake.usgs.gov/data/comcat/",
    ),
)


def _iso_from_millis(value: Any) -> str | None:
    try:
        millis = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(millis):
        return None
    return (
        datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _safe_usgs_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "earthquake.usgs.gov":
        return None
    return value


def _point(raw: Any) -> tuple[dict[str, Any] | None, float | None]:
    if not isinstance(raw, dict) or raw.get("type") != "Point":
        return None, None
    coords = raw.get("coordinates")
    if not isinstance(coords, list) or len(coords) < 2:
        return None, None
    try:
        longitude = float(coords[0])
        latitude = float(coords[1])
        depth = float(coords[2]) if len(coords) > 2 and coords[2] is not None else None
    except (TypeError, ValueError):
        return None, None
    if not (
        isfinite(longitude)
        and isfinite(latitude)
        and -180 <= longitude <= 180
        and -90 <= latitude <= 90
    ):
        return None, None
    if depth is not None and not isfinite(depth):
        depth = None
    return {"type": "Point", "coordinates": [longitude, latitude]}, depth


def _hazard_type(event_type: str) -> str:
    value = event_type.casefold()
    if "explosion" in value or "blast" in value:
        return "seismic_explosion"
    if "collapse" in value or "rock burst" in value:
        return "collapse"
    if any(token in value for token in ("debris flow", "mudflow", "mud slide", "mudslide")):
        return "debris_flow"
    if "landslide" in value or "rock slide" in value or "rockslide" in value:
        return "landslide"
    if "avalanche" in value:
        return "avalanche"
    if "meteor" in value:
        return "meteor"
    if "volcan" in value:
        return "volcanic_activity"
    if "sonic" in value or "acoustic" in value:
        return "acoustic_event"
    return "seismic_non_earthquake"


def _point_in_bbox(
    geometry: dict[str, Any] | None,
    bbox: tuple[float, float, float, float] | None,
) -> bool:
    if bbox is None or geometry is None:
        return True
    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or len(coords) < 2:
        return True
    longitude = float(coords[0])
    latitude = float(coords[1])
    west, south, east, north = bbox
    longitude_ok = (
        west <= longitude <= east
        if west <= east
        else longitude >= west or longitude <= east
    )
    return longitude_ok and south <= latitude <= north


def _event(feature: Any) -> dict[str, Any] | None:
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties")
    if not isinstance(props, dict):
        return None
    event_type = str(props.get("type") or "").strip()
    if not event_type or event_type.casefold() == "earthquake":
        return None

    geometry, depth_km = _point(feature.get("geometry"))
    place = str(props.get("place") or "Ort nicht angegeben")
    magnitude = props.get("mag")
    hazard_type = _hazard_type(event_type)
    title = str(props.get("title") or "").strip()
    if not title:
        title = f"{event_type} · {place}"

    return {
        "id": str(feature.get("id") or props.get("code") or title),
        "hazard_type": hazard_type,
        "volcano_semantics": (
            volcano_semantics(
                "seismic_catalog_volcanic_event",
                source_event_type=event_type,
            )
            if hazard_type == "volcanic_activity"
            else None
        ),
        "event": event_type,
        "headline": title,
        "severity": "unknown",
        "urgency": "unknown",
        "certainty": "observed",
        "status": str(props.get("status") or "actual").casefold(),
        "message_type": "event",
        # Ein seismisches Ereignis hat keine automatisch belegte
        # Meldungs-Ausstellungszeit. Ursprung und Quellupdate getrennt halten.
        "sent": None,
        "effective": _iso_from_millis(props.get("time")),
        "onset": _iso_from_millis(props.get("time")),
        "last_updated_at": _iso_from_millis(props.get("updated")),
        "expires": None,
        "ends": None,
        "area_desc": place,
        "geometry": geometry,
        "description": None,
        "instruction": None,
        "sender_name": "USGS / ANSS Comprehensive Earthquake Catalog",
        "response": "monitor",
        "affected_zones": [],
        "source_semantics": "observed_seismic_catalog_event",
        "parameters": {
            "usgs_event_type": event_type,
            "magnitude": magnitude,
            "magnitude_type": props.get("magType"),
            "depth_km": depth_km,
            "significance": props.get("sig"),
            "network": props.get("net"),
            "code": props.get("code"),
            "classification_note": (
                "USGS seismic catalog classification only; WeatherRouter does not infer "
                "attack, intent, military origin or criminal cause."
            ),
        },
        "web_url": _safe_usgs_url(props.get("url")),
    }


class UsgsSeismicEventsProvider:
    """Expose explicitly classified non-earthquake USGS seismic events."""

    id = "usgs_seismic_events"
    name = "USGS · Seismische Sonderereignisse"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Der USGS/ANSS-Katalog enthält neben Erdbeben auch ausdrücklich als "
                "andere Ereignistypen klassifizierte seismische Signale. WeatherRouter "
                "zeigt nur diese Quellklassifikation und deutet keine Ursache hinzu."
            ),
            coverage="Global soweit USGS/ANSS katalogisiert",
            strengths=(
                "strukturierte USGS-Ereignistypen",
                "kartierbare Punktdaten",
                "keine semantische Hochstufung zu Anschlag oder militärischem Ereignis",
            ),
            limitations=(
                "nicht als Vollerfassung von Explosionen oder Unfällen geeignet",
                "Katalogklassifikationen können nachträglich aktualisiert werden",
            ),
            documentation_url="https://earthquake.usgs.gov/data/comcat/",
            attribution="U.S. Geological Survey · ANSS ComCat",
            services=(
                {
                    "name": "USGS all-day GeoJSON · Nicht-Erdbeben",
                    "status": "integriert",
                    "note": "expliziter On-Demand-Abruf; standardmäßig deaktiviert",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="non_earthquake_seismic_events",
                scheme="https",
                host="earthquake.usgs.gov",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=(_CAPABILITY_ID,),
                note="USGS all-day GeoJSON, gefiltert auf type != earthquake.",
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
            raise ValueError(f"Unsupported USGS seismic capability: {capability_id}")

        session = async_get_clientsession(hass)
        async with session.get(
            _FEED_URL,
            headers={
                "Accept": "application/geo+json,application/json,*/*",
                "User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev)",
            },
            timeout=20,
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)

        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            raise ValueError("USGS GeoJSON feed has no feature list")

        events = []
        for feature in features:
            item = _event(feature)
            if item is None or not _point_in_bbox(item.get("geometry"), bbox):
                continue
            events.append(item)

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
                "usgs_event_type_filter": "type != earthquake",
                "classification_only": True,
                "bbox_filtered": bbox is not None,
            },
            "attribution": "U.S. Geological Survey · ANSS Comprehensive Earthquake Catalog",
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
            "stage": "usgs_non_earthquake_geojson",
            "provider_revision": _PROVIDER_REVISION,
            "event_count": feed.get("event_count", 0),
            "sample": [
                {
                    "event": item.get("event"),
                    "headline": item.get("headline"),
                    "has_geometry": isinstance(item.get("geometry"), dict),
                }
                for item in feed.get("events", [])[:5]
            ],
        }
