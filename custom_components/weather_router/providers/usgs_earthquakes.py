"""USGS global earthquake GeoJSON hazard provider."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import earthquake_semantics

_PROVIDER_REVISION = "wr-0.10.130-quake-semantics-1"
_FEEDS = {
    "earthquakes_past_day": (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
    ),
    "significant_earthquakes_past_month": (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson"
    ),
}

_CAPABILITIES = (
    CapabilityInfo(
        id="earthquakes_past_day",
        name="Erdbeben weltweit · letzte 24 Stunden",
        unit=None,
        source_class="observation",
        render_mode="hazard_feed",
        description=(
            "USGS-GeoJSON-Ereignisse des letzten Tages. Quarry blasts und andere "
            "Nicht-Erdbeben-Ereignistypen werden nicht als Erdbeben ausgegeben."
        ),
        coverage="Global",
        temporal_resolution="laufend aktualisierter 24-h-Feed",
        strengths=(
            "offizielle USGS Earthquake Hazards Program Quelle",
            "Magnitude, Tiefe, Ort, Zeit und GeoJSON-Koordinate",
            "USGS-PAGER-Farbe und Tsunami-Flag werden erhalten, soweit vorhanden",
        ),
        limitations=(
            "Magnitude-basierte WeatherRouter-Schwere ist eine Darstellungsstaffelung und "
            "keine amtliche Schadens- oder Gefahrenwarnstufe",
            "sehr kleine Ereignisse hängen von der Erfassung durch die seismischen Netze ab",
        ),
        documentation_url="https://earthquake.usgs.gov/earthquakes/feed/",
    ),
    CapabilityInfo(
        id="significant_earthquakes_past_month",
        name="Bedeutende Erdbeben weltweit · letzte 30 Tage",
        unit=None,
        source_class="observation",
        render_mode="hazard_feed",
        description=(
            "USGS-Auswahl bedeutender Erdbeben des vergangenen Monats als kompakter "
            "weltweiter Ereignisfeed."
        ),
        coverage="Global",
        temporal_resolution="laufend aktualisierter Monatsfeed",
        strengths=(
            "offizielle USGS-Auswahl bedeutender Ereignisse",
            "geeignet für eine ruhige weltweite Übersicht",
        ),
        limitations=(
            "die USGS-Bedeutend-Auswahl ist kein vollständiger Erdbebenkatalog",
        ),
        documentation_url="https://earthquake.usgs.gov/earthquakes/feed/",
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


def _severity_from_magnitude(value: Any) -> tuple[str, str]:
    try:
        magnitude = float(value)
    except (TypeError, ValueError):
        return "unknown", "unknown"
    if not isfinite(magnitude):
        return "unknown", "unknown"
    if magnitude >= 7.0:
        return "extreme", "M7+"
    if magnitude >= 6.0:
        return "severe", "M6"
    if magnitude >= 5.0:
        return "moderate", "M5"
    return "minor", "unter M5"


def _point_from_geometry(raw: Any) -> tuple[dict[str, Any] | None, float | None]:
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
    longitude_ok = west <= longitude <= east if west <= east else (
        longitude >= west or longitude <= east
    )
    return longitude_ok and south <= latitude <= north


def _event_from_feature(
    feature: Any,
    *,
    catalog_selection: str,
) -> dict[str, Any] | None:
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties")
    if not isinstance(props, dict):
        return None
    event_type = str(props.get("type") or "earthquake").casefold()
    if event_type != "earthquake":
        return None

    geometry, depth_km = _point_from_geometry(feature.get("geometry"))
    magnitude = props.get("mag")
    severity, magnitude_band = _severity_from_magnitude(magnitude)
    place = str(props.get("place") or "Ort nicht angegeben")
    title = str(props.get("title") or "").strip()
    if not title:
        title = f"Erdbeben M{magnitude} · {place}" if magnitude is not None else f"Erdbeben · {place}"

    event_time = _iso_from_millis(props.get("time"))
    updated = _iso_from_millis(props.get("updated"))
    pager = props.get("alert")
    pager = str(pager).casefold() if isinstance(pager, str) and pager else None
    quake_semantics = earthquake_semantics(
        "seismic_catalog_earthquake_event",
        catalog_selection=catalog_selection,
        magnitude=magnitude,
        magnitude_type=props.get("magType"),
        depth_km=depth_km,
        felt_reports=props.get("felt"),
        community_intensity_cdi=props.get("cdi"),
        instrumental_intensity_mmi=props.get("mmi"),
        pager_alert=pager,
        significance=props.get("sig"),
        tsunami_flag=bool(props.get("tsunami")),
        source_status=props.get("status"),
        catalog_updated=updated,
        legacy_magnitude_display_band=magnitude_band,
    )

    return {
        "id": str(feature.get("id") or props.get("code") or title),
        "hazard_type": "earthquake",
        "earthquake_semantics": quake_semantics,
        "event": "Earthquake",
        "headline": title,
        "severity": severity,
        "urgency": "immediate",
        "certainty": "observed",
        "status": "actual",
        "message_type": "event",
        "sent": updated or event_time,
        "effective": event_time,
        "onset": event_time,
        "expires": None,
        "ends": None,
        "area_desc": place,
        "geometry": geometry,
        "description": (
            f"Magnitude {magnitude if magnitude is not None else 'unbekannt'}"
            + (f" · Tiefe {depth_km:g} km" if depth_km is not None else "")
            + f" · {place}"
        ),
        "instruction": None,
        "sender_name": "USGS Earthquake Hazards Program",
        "response": None,
        "affected_zones": [],
        "parameters": {
            "magnitude": magnitude,
            "magnitude_type": props.get("magType"),
            "magnitude_band": magnitude_band,
            "severity_basis": "weather_router_magnitude_display_band",
            "depth_km": depth_km,
            "felt_reports": props.get("felt"),
            "community_intensity_cdi": props.get("cdi"),
            "instrumental_intensity_mmi": props.get("mmi"),
            "pager_alert": pager,
            "significance": props.get("sig"),
            "tsunami_flag": bool(props.get("tsunami")),
            "usgs_status": props.get("status"),
            "network": props.get("net"),
            "code": props.get("code"),
        },
        "web_url": _safe_usgs_url(props.get("url")),
    }


class UsgsEarthquakeProvider:
    """Expose official USGS earthquake summary feeds through hazard_feed."""

    id = "usgs_earthquakes"
    name = "USGS · Erdbeben"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Das USGS Earthquake Hazards Program veröffentlicht laufend aktualisierte "
                "GeoJSON-Zusammenfassungen weltweiter Erdbeben."
            ),
            coverage="Global",
            strengths=(
                "weltweiter maschinenlesbarer Ereignisfeed",
                "Magnitude, Tiefe, Zeit und Epizentrum",
                "USGS-Ereignislink sowie PAGER-/Tsunami-Metadaten soweit vorhanden",
            ),
            limitations=(
                "WeatherRouter leitet aus der Magnitude nur eine visuelle Schwereklasse ab; "
                "sie ist keine amtliche Warnstufe",
                "der 24-h-Feed ist absichtlich zeitlich begrenzt",
            ),
            documentation_url="https://earthquake.usgs.gov/earthquakes/feed/",
            attribution="U.S. Geological Survey · Earthquake Hazards Program",
            services=(
                {
                    "name": "GeoJSON Summary · All Earthquakes, Past Day",
                    "status": "integriert",
                    "note": "weltweiter 24-h-Erdbebenfeed",
                },
                {
                    "name": "GeoJSON Summary · Significant, Past Month",
                    "status": "integriert",
                    "note": "kompakte Auswahl bedeutender Ereignisse",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="earthquake_hazard_feeds",
                scheme="https",
                host="earthquake.usgs.gov",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=tuple(_FEEDS),
                note="Official USGS Earthquake Hazards Program GeoJSON summary feeds.",
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
        url = _FEEDS.get(capability_id)
        if url is None:
            raise ValueError(f"Unsupported USGS earthquake capability: {capability_id}")

        session = async_get_clientsession(hass)
        async with session.get(
            url,
            headers={"Accept": "application/geo+json,application/json"},
            timeout=20,
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)

        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise ValueError("USGS earthquake response is not a GeoJSON FeatureCollection")

        events: list[dict[str, Any]] = []
        for feature in payload.get("features", []):
            event = _event_from_feature(
                feature,
                catalog_selection=(
                    "significant_month"
                    if capability_id == "significant_earthquakes_past_month"
                    else "all_day"
                ),
            )
            if event is None or not _point_in_bbox(event.get("geometry"), bbox):
                continue
            events.append(event)

        events.sort(key=lambda item: str(item.get("effective") or ""), reverse=True)
        maximum = max(1, min(int(limit), 1000))
        events = events[:maximum]
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

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
                "feed_title": metadata.get("title"),
                "generated": _iso_from_millis(metadata.get("generated")),
                "source_count": metadata.get("count"),
                "bbox_filtered": bbox is not None,
            },
            "attribution": "U.S. Geological Survey · Earthquake Hazards Program",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        selected = capability_id or "earthquakes_past_day"
        if selected not in _FEEDS:
            return {
                "ok": False,
                "stage": "capability_selection",
                "provider_revision": _PROVIDER_REVISION,
            }
        feed = await self.async_get_hazard_feed(hass, selected, limit=25)
        return {
            "ok": True,
            "stage": "usgs_geojson_summary",
            "provider_revision": _PROVIDER_REVISION,
            "capability": selected,
            "event_count": feed.get("event_count", 0),
            "sample": [
                {
                    "headline": item.get("headline"),
                    "magnitude": (item.get("parameters") or {}).get("magnitude"),
                    "depth_km": (item.get("parameters") or {}).get("depth_km"),
                    "effective": item.get("effective"),
                    "has_geometry": isinstance(item.get("geometry"), dict),
                }
                for item in feed.get("events", [])[:5]
            ],
        }
