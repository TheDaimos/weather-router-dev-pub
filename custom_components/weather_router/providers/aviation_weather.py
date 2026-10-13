"""NOAA/NWS Aviation Weather Center SIGMET/AIRMET hazard provider."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import geometry_intersects_bbox

_PROVIDER_REVISION = "wr-0.10.127-tropical-semantics-1"
_ENDPOINTS = {
    "international_sigmet_worldwide": "https://aviationweather.gov/api/data/isigmet?format=geojson",
    "us_airsigmet_current": "https://aviationweather.gov/api/data/airsigmet?format=geojson",
    "us_gairmet_current": "https://aviationweather.gov/api/data/gairmet?format=geojson",
}

_CAPABILITIES = (
    CapabilityInfo(
        id="international_sigmet_worldwide",
        name="Internationale SIGMETs · weltweit",
        unit=None,
        source_class="official_warning",
        render_mode="hazard_feed",
        description=(
            "Aktuelle internationale SIGMET-Flächen aus dem NOAA/NWS Aviation Weather Center."
        ),
        coverage="Weltweit · internationale SIGMETs",
        temporal_resolution="laufend aktualisierte Luftfahrtwarnungen",
        strengths=(
            "offizielle Aviation-Weather-Quelle",
            "GeoJSON-Flächen und Gültigkeitszeiträume",
            "u. a. Gewitter, Turbulenz, Vereisung, Vulkanasche und tropische Wirbelstürme",
        ),
        limitations=(
            "Luftfahrtwarnung, keine allgemeine Bevölkerungswarnung",
            "Höhenbänder und luftfahrtspezifische Bedeutung müssen erhalten bleiben",
        ),
        documentation_url="https://aviationweather.gov/data/api/",
    ),
    CapabilityInfo(
        id="us_airsigmet_current",
        name="USA · SIGMET/AIRMET · aktuell",
        unit=None,
        source_class="official_advisory",
        render_mode="hazard_feed",
        description=(
            "Aktuelle US-SIGMET-/AIRMET-Flächen aus dem NOAA/NWS Aviation Weather Center."
        ),
        coverage="USA und angrenzende Luftfahrtgebiete",
        temporal_resolution="laufend aktualisierte Luftfahrtwarnungen/-hinweise",
        strengths=(
            "offizielle Aviation-Weather-Quelle",
            "GeoJSON-Flächen, Höhen und Gültigkeitszeiträume",
        ),
        limitations=(
            "AIRMET und SIGMET bleiben als Produkttyp getrennt",
            "nicht als allgemeine Bevölkerungsschutzwarnung interpretieren",
        ),
        documentation_url="https://aviationweather.gov/data/api/",
    ),
    CapabilityInfo(
        id="us_gairmet_current",
        name="USA · G-AIRMET · aktuell",
        unit=None,
        source_class="official_advisory",
        render_mode="hazard_feed",
        description=(
            "Aktuelle grafische AIRMET-Hinweise (G-AIRMET) für die zusammenhängenden "
            "48 US-Bundesstaaten aus dem NOAA/NWS Aviation Weather Center."
        ),
        coverage="Contiguous 48 United States",
        temporal_resolution="laufend aktualisierte Luftfahrthinweise",
        strengths=(
            "offizielle NOAA/NWS-Quelle",
            "GeoJSON-Flächen mit höherer räumlich-zeitlicher Präzision als alte Text-AIRMETs",
        ),
        limitations=(
            "Luftfahrthinweis, keine allgemeine Bevölkerungswarnung",
            "G-AIRMETs ersetzen seit Januar 2025 die CONUS Text-AIRMETs",
        ),
        documentation_url="https://aviationweather.gov/data/api/",
    ),

)


def _hazard_type(value: Any) -> str:
    text = str(value or "").strip().casefold()
    mapping = {
        "convective": "severe_thunderstorm",
        "conv": "severe_thunderstorm",
        "thunderstorm": "severe_thunderstorm",
        "va": "volcanic_ash",
        "volcanic ash": "volcanic_ash",
        "tc": "tropical_cyclone",
        "tropical cyclone": "tropical_cyclone",
        "ice": "aviation_icing",
        "icing": "aviation_icing",
        "turb": "aviation_turbulence",
        "turbulence": "aviation_turbulence",
        "mtw": "mountain_wave",
        "mountain wave": "mountain_wave",
        "dust": "dust_storm",
        "sand": "dust_storm",
        "ifr": "aviation_ifr",
    }
    if text in mapping:
        return mapping[text]
    for needle, hazard_type in mapping.items():
        if needle in text:
            return hazard_type
    return "aviation_warning"


def _event_from_feature(feature: Any, *, capability_id: str) -> dict[str, Any] | None:
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(props, dict):
        props = {}
    if not isinstance(geometry, dict):
        geometry = None

    product_type = str(
        props.get("airSigmetType")
        or props.get("data")
        or (
            "SIGMET"
            if capability_id == "international_sigmet_worldwide"
            else "G-AIRMET"
            if capability_id == "us_gairmet_current"
            else "AIRMET/SIGMET"
        )
    ).strip()
    hazard = str(props.get("hazard") or "Aviation hazard").strip()
    icao = str(props.get("icaoId") or "").strip()
    identifier = str(
        feature.get("id")
        or props.get("id")
        or props.get("alphaChar")
        or f"{icao}:{hazard}:{props.get('validTimeFrom')}"
    )

    headline = " · ".join(
        part for part in (product_type, hazard, icao) if part
    )
    raw_text = props.get("rawAirSigmet") or props.get("rawISigmet") or props.get("rawText")
    if isinstance(raw_text, str):
        raw_text = " ".join(raw_text.split())[:8000]
    else:
        raw_text = None

    hazard_type = _hazard_type(hazard)
    return {
        "id": f"awc:{capability_id}:{identifier}",
        "hazard_type": hazard_type,
        "tropical_system": (
            {
                "system_class": "tropical_cyclone_unspecified",
                "source_classification": hazard,
                "classification_source": "explicit_event_text",
            }
            if hazard_type == "tropical_cyclone"
            else None
        ),
        "event": product_type,
        "headline": headline or "Aviation warning",
        "severity": "unknown",
        "urgency": "expected",
        "certainty": "forecast",
        "status": "actual",
        "message_type": "warning" if "SIGMET" in product_type.upper() else "advisory",
        "sent": props.get("receiptTime"),
        "effective": props.get("validTimeFrom"),
        "onset": props.get("validTimeFrom"),
        "expires": props.get("validTimeTo"),
        "ends": props.get("validTimeTo"),
        "area_desc": icao or None,
        "geometry": geometry,
        "description": raw_text,
        "instruction": None,
        "sender_name": "NOAA/NWS Aviation Weather Center",
        "response": "monitor",
        "affected_zones": [],
        "source_semantics": "official_aviation_warning",
        "parameters": {
            "product_type": product_type,
            "hazard": hazard,
            "source_severity": props.get("severity"),
            "icao_id": icao or None,
            "altitude_low_ft": props.get("altitudeLow1"),
            "altitude_high_ft": props.get("altitudeHi1") or props.get("altitudeHi2"),
            "movement_direction_deg": props.get("movementDir"),
            "movement_speed_kt": props.get("movementSpd"),
            "classification_note": (
                "Aviation warning/advisory; not a general public warning."
            ),
        },
        "web_url": "https://aviationweather.gov/",
    }


class AviationWeatherProvider:
    """Expose current AWC SIGMET/AIRMET GeoJSON as explicit aviation hazards."""

    id = "aviation_weather"
    name = "NOAA/NWS · Aviation Weather Center"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Das NOAA/NWS Aviation Weather Center veröffentlicht aktuelle "
                "SIGMET-/AIRMET-Daten. WeatherRouter erhält die Luftfahrtsemantik "
                "und stellt diese nicht als allgemeine Bevölkerungswarnung dar."
            ),
            coverage="Weltweit (International SIGMET) sowie USA (AIRMET/SIGMET/G-AIRMET)",
            strengths=(
                "offizielle NOAA/NWS-Quelle",
                "GeoJSON-Warnflächen",
                "Gültigkeitszeit, Höhenband und Bewegungsdaten soweit vorhanden",
            ),
            limitations=(
                "fachlich für Luftfahrt bestimmt",
                "nicht jeder Luftfahrt-Hazard bedeutet eine Gefahr am Boden",
            ),
            documentation_url="https://aviationweather.gov/data/api/",
            attribution="NOAA / National Weather Service · Aviation Weather Center",
            services=(
                {
                    "name": "International SIGMET GeoJSON",
                    "status": "integriert",
                    "note": "weltweit",
                },
                {
                    "name": "US AIRMET/SIGMET GeoJSON",
                    "status": "integriert",
                    "note": "USA / angrenzende Luftfahrtgebiete",
                },
                {
                    "name": "US G-AIRMET GeoJSON",
                    "status": "integriert",
                    "note": "Contiguous 48 United States",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="aviation_weather_warnings",
                scheme="https",
                host="aviationweather.gov",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=tuple(_ENDPOINTS),
                note="NOAA/NWS Aviation Weather Data API · GeoJSON.",
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
        endpoint = _ENDPOINTS.get(capability_id)
        if endpoint is None:
            raise ValueError(f"Unsupported Aviation Weather capability: {capability_id}")

        session = async_get_clientsession(hass)
        async with session.get(
            endpoint,
            headers={
                "Accept": "application/geo+json,application/json,*/*",
                "User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)",
            },
            timeout=25,
        ) as response:
            if response.status == 204:
                payload: Any = {"type": "FeatureCollection", "features": []}
            else:
                response.raise_for_status()
                payload = await response.json(content_type=None)

        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list):
            raise ValueError("Aviation Weather GeoJSON response has no feature list")

        events: list[dict[str, Any]] = []
        for feature in features:
            event = _event_from_feature(feature, capability_id=capability_id)
            if event is None or not geometry_intersects_bbox(event.get("geometry"), bbox):
                continue
            events.append(event)

        maximum = max(1, min(int(limit), 1000))
        events = events[:maximum]
        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": (
                "official_warning"
                if capability_id == "international_sigmet_worldwide"
                else "official_advisory"
            ),
            "render_mode": "hazard_feed",
            "coverage_status": "viewport_filtered" if bbox is not None else "provider_coverage",
            "events": events,
            "event_count": len(events),
            "provider_metadata": {
                "aviation_only": True,
                "bbox_filtered": bbox is not None,
                "rate_limit_documented": "100 requests/minute",
            },
            "attribution": "NOAA / National Weather Service · Aviation Weather Center",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        targets = [capability_id] if capability_id else list(_ENDPOINTS)
        results: list[dict[str, Any]] = []
        for target in targets:
            if target not in _ENDPOINTS:
                return {"ok": False, "stage": "capability_selection"}
            feed = await self.async_get_hazard_feed(hass, target, limit=25)
            results.append(
                {
                    "capability": target,
                    "event_count": feed.get("event_count", 0),
                    "hazard_types": sorted(
                        {
                            item.get("hazard_type")
                            for item in feed.get("events", [])
                            if item.get("hazard_type")
                        }
                    ),
                }
            )
        return {
            "ok": True,
            "stage": "aviationweather_sigmet_geojson",
            "provider_revision": _PROVIDER_REVISION,
            "results": results,
        }
