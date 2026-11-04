"""NOAA National Hurricane Center active tropical cyclone hazard feed."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import tropical_system_from_classification

_CURRENT_STORMS = "https://www.nhc.noaa.gov/CurrentStorms.json"
_PROVIDER_REVISION = "wr-0.10.128-tropical-semantics-2"

_CAPABILITIES = (
    CapabilityInfo(
        id="active_tropical_cyclones",
        name="Aktive tropische Wirbelstürme · NHC",
        unit=None,
        source_class="warning",
        render_mode="hazard_feed",
        description=(
            "Aktive tropische Depressionen, Tropenstürme und Hurrikane des NOAA "
            "National Hurricane Center einschließlich amtlicher GIS-Ressourcen."
        ),
        coverage="Atlantik, östlicher und zentraler Nordpazifik gemäß NHC-Zuständigkeit",
        temporal_resolution="advisory-gesteuert",
        strengths=(
            "amtliche NHC-Quelle",
            "aktuelle Sturmposition, Intensität, Luftdruck und Zugbewegung",
            "Links auf Track, Unsicherheitskegel, Windfelder sowie Watches/Warnings",
        ),
        limitations=(
            "andere globale Tropensturmbecken werden von anderen zuständigen Warnzentren abgedeckt",
        ),
        documentation_url="https://www.nhc.noaa.gov/gis/",
    ),
)


def _safe_nhc_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {
        "www.nhc.noaa.gov",
        "nhc.noaa.gov",
    }:
        return None
    return value


def _resource(block: Any) -> dict[str, Any] | None:
    if not isinstance(block, dict):
        return None
    result: dict[str, Any] = {}
    for key in (
        "advNum",
        "issuance",
        "fileUpdateTime",
        "url",
        "zipFile",
        "zipFile5km",
        "zipFile0p5deg",
        "kmzFile",
        "kmzFile34kt",
        "kmzFile50kt",
        "kmzFile64kt",
    ):
        value = block.get(key)
        if key.lower().endswith(("url", "file", "5km", "0p5deg", "34kt", "50kt", "64kt")):
            safe = _safe_nhc_url(value)
            if safe is not None:
                result[key] = safe
        elif value is not None:
            result[key] = value
    return result or None


class NhcTropicalCycloneProvider:
    """Expose NHC current storms through the generic WeatherRouter hazard contract."""

    id = "nhc_tropical_cyclones"
    name = "NOAA · National Hurricane Center"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Das NOAA National Hurricane Center veröffentlicht aktuelle Tropenstürme "
                "und Hurrikane einschließlich amtlicher Forecast-/GIS-Produkte."
            ),
            coverage="Atlantik sowie östlicher/zentraler Nordpazifik gemäß NHC-Zuständigkeit",
            strengths=(
                "amtliche Tropensturmquelle",
                "aktive Systeme mit Position und Intensität",
                "Track, Cone, Watches/Warnings, Windfelder und Sturmflutprodukte soweit verfügbar",
            ),
            limitations=(
                "kein weltweites Tropensturmzentrum für alle Ozeanbecken",
                "einzelne GIS-Produkte existieren nur bei entsprechendem Ereignis",
            ),
            documentation_url="https://www.nhc.noaa.gov/gis/",
            attribution="NOAA / National Hurricane Center",
            services=(
                {
                    "name": "CurrentStorms JSON",
                    "status": "integriert",
                    "note": "aktive Tropenstürme/Hurrikane als hazard_feed",
                },
                {
                    "name": "NHC GIS",
                    "status": "verknüpft",
                    "note": "Track, Cone, Watches/Warnings, Windfelder, Sturmflut",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="tropical_cyclone_hazards",
                scheme="https",
                host="www.nhc.noaa.gov",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=("active_tropical_cyclones",),
                note="NHC CurrentStorms JSON plus official GIS resource links.",
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
        if capability_id != "active_tropical_cyclones":
            raise ValueError(f"Unsupported NHC hazard capability: {capability_id}")

        session = async_get_clientsession(hass)
        async with session.get(
            _CURRENT_STORMS,
            headers={"Accept": "application/json"},
            timeout=20,
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)

        storms = payload.get("activeStorms")
        if not isinstance(storms, list):
            raise ValueError("NHC CurrentStorms response has no activeStorms array")

        maximum = max(1, min(int(limit), 100))
        events: list[dict[str, Any]] = []
        for storm in storms:
            if not isinstance(storm, dict):
                continue
            lat = storm.get("latitudeNumeric")
            lon = storm.get("longitudeNumeric")
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue

            if bbox is not None:
                west, south, east, north = bbox
                longitude_match = (
                    west <= float(lon) <= east
                    if west <= east
                    else float(lon) >= west or float(lon) <= east
                )
                if not (longitude_match and south <= float(lat) <= north):
                    continue

            classification = str(storm.get("classification") or "").strip()
            name = str(storm.get("name") or "").strip()
            intensity = storm.get("intensity")
            tropical_system = tropical_system_from_classification(
                classification,
                classification_source="structured_provider_field",
                fallback_unspecified=True,
            )
            resources = {
                key: item
                for key, item in {
                    "public_advisory": _resource(storm.get("publicAdvisory")),
                    "forecast_advisory": _resource(storm.get("forecastAdvisory")),
                    "forecast_discussion": _resource(storm.get("forecastDiscussion")),
                    "forecast_track": _resource(storm.get("forecastTrack")),
                    "track_cone": _resource(storm.get("trackCone")),
                    "wind_watches_warnings": _resource(storm.get("windWatchesWarnings")),
                    "initial_wind_extent": _resource(storm.get("initialWindExtent")),
                    "forecast_wind_radii": _resource(storm.get("forecastWindRadiiGIS")),
                    "wind_speed_probabilities": _resource(storm.get("windSpeedProbabilitiesGIS")),
                    "storm_surge_watch_warning": _resource(storm.get("stormSurgeWatchWarningGIS")),
                    "potential_storm_surge_flooding": _resource(
                        storm.get("potentialStormSurgeFloodingGIS")
                    ),
                    "peak_surge": _resource(storm.get("peakSurgeKML")),
                }.items()
                if item is not None
            }
            public_advisory = resources.get("public_advisory") or {}
            events.append(
                {
                    "id": str(storm.get("id") or ""),
                    "hazard_type": "tropical_cyclone",
                    "event": "Tropical Cyclone",
                    "headline": " ".join(
                        part for part in (classification, name) if part
                    ) or "Active Tropical Cyclone",
                    "severity": "unknown",
                    "urgency": "immediate",
                    "certainty": "observed",
                    "status": "actual",
                    "message_type": "update",
                    "sent": None,  # NHC lastUpdate ist Status-Gültigkeit, kein Bulletin-Ausstellungszeitpunkt.
                    "effective": storm.get("lastUpdate"),
                    "onset": None,
                    "expires": None,
                    "ends": None,
                    "area_desc": None,
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(lon), float(lat)],
                    },
                    "description": None,
                    "instruction": None,
                    "sender_name": "NOAA / National Hurricane Center",
                    "response": "monitor",
                    "affected_zones": [],
                    "tropical_system": tropical_system,
                    "parameters": {
                        "classification": classification or None,
                        "intensity_kt": intensity,
                        "pressure_hpa": storm.get("pressure"),
                        "movement_direction_deg": storm.get("movementDir"),
                        "movement_speed_kt": storm.get("movementSpeed"),
                        "bin_number": storm.get("binNumber"),
                        "resources": resources,
                    },
                    "web_url": public_advisory.get("url"),
                }
            )
            if len(events) >= maximum:
                break

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "warning",
            "render_mode": "hazard_feed",
            "coverage_status": "regional",
            "events": events,
            "event_count": len(events),
            "attribution": "NOAA / National Hurricane Center",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        selected = capability_id or "active_tropical_cyclones"
        feed = await self.async_get_hazard_feed(
            hass,
            selected,
            limit=10,
        )
        return {
            "ok": True,
            "stage": "current_storms",
            "provider_revision": _PROVIDER_REVISION,
            "active_storm_count": feed.get("event_count", 0),
            "events": [
                {
                    "id": item.get("id"),
                    "headline": item.get("headline"),
                    "classification": (item.get("parameters") or {}).get("classification"),
                    "has_track": "forecast_track" in ((item.get("parameters") or {}).get("resources") or {}),
                    "has_cone": "track_cone" in ((item.get("parameters") or {}).get("resources") or {}),
                    "has_watches_warnings": "wind_watches_warnings" in ((item.get("parameters") or {}).get("resources") or {}),
                }
                for item in feed.get("events", [])
            ],
        }
