"""NASA Moon Trek planetary tile provider for WeatherRouter."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_LAYER_ID = "LRO_WAC_Mosaic_Global_303ppd_v02"
_TILE_TEMPLATE = (
    "https://trek.nasa.gov/tiles/Moon/EQ/"
    f"{_LAYER_ID}/1.0.0/default/default028mm/"
    "{z}/{y}/{x}.jpg"
)
_CAPABILITIES_URL = (
    "https://trek.nasa.gov/tiles/Moon/EQ/"
    f"{_LAYER_ID}/1.0.0/WMTSCapabilities.xml"
)
_USER_AGENT = "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)"

_CAPABILITIES = (
    CapabilityInfo(
        id="moon_lro_wac_global",
        name="Moon Trek · LRO WAC Global",
        unit=None,
        source_class="reference_imagery",
        render_mode="planetary_tile",
        description=(
            "Globale equirektangulare Mondmosaik der Lunar Reconnaissance Orbiter Camera (WAC)."
        ),
        coverage="Mond · global",
        temporal_resolution="statische Referenzmosaik",
        strengths=(
            "globale Mondoberfläche",
            "offizieller NASA Moon Trek WMTS",
            "mehrstufiges Zoom-Kachelraster",
        ),
        limitations=(
            "keine Echtzeitdaten",
            "Mondkoordinaten statt Erdkoordinaten",
            "eigener planetarer Viewer erforderlich",
        ),
        documentation_url="https://trek.nasa.gov/moon/",
    ),
)


class NasaMoonProvider:
    """NASA Solar System Treks adapter for the Moon."""

    id = "nasa_moon"
    name = "NASA · Moon Trek"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "NASA Moon Trek bündelt kartierbare Mondoberflächen- und Messdaten. "
                "WeatherRouter integriert zunächst die globale LRO-WAC-Mosaik als eigenen "
                "planetaren Kachelviewer."
            ),
            coverage="Mond · global",
            strengths=(
                "offizielle NASA/JPL-Trek-Plattform",
                "OGC-WMTS-Kacheldienst",
                "globale Mondnavigation mit mehreren Zoomstufen",
            ),
            limitations=(
                "nicht mit der normalen Web-Mercator-Erdkarte identisch",
                "statische Referenzmosaik statt Livebild",
                "weitere Moon-Trek-Layer werden separat freigegeben",
            ),
            documentation_url="https://trek.nasa.gov/moon/",
            attribution="NASA/JPL Moon Trek · LRO WAC",
            services=(
                {
                    "name": "LRO WAC Global Mosaic",
                    "status": "integriert",
                    "note": "globale equirektangulare WMTS-Mondkarte",
                },
                {
                    "name": "Weitere Moon-Trek-Ebenen",
                    "status": "vorgemerkt",
                    "note": "Topografie, Beleuchtung und Missionsdaten später über denselben Vertrag",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="planetary_moon_tiles",
                scheme="https",
                host="trek.nasa.gov",
                port=443,
                target_type="frontend_tile",
                required=True,
                capabilities=("moon_lro_wac_global",),
                note="NASA Moon Trek WMTS-Kacheln und GetCapabilities.",
            ),
        )

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id not in {None, "moon_lro_wac_global"}:
            return {
                "ok": False,
                "stage": "capability_selection",
                "error": {
                    "type": "ValueError",
                    "message": f"Unsupported NASA Moon capability: {capability_id}",
                },
            }

        session = async_get_clientsession(hass)
        try:
            async with session.get(
                _CAPABILITIES_URL,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "application/xml,text/xml,*/*",
                },
                timeout=20,
            ) as response:
                response.raise_for_status()
                xml = await response.text()
        except Exception as err:  # noqa: BLE001 - explicit diagnostics capture
            return {
                "ok": False,
                "stage": "wmts_capabilities",
                "error": {
                    "type": type(err).__name__,
                    "message": str(err),
                },
            }

        present = _LAYER_ID in xml and "Capabilities" in xml
        return {
            "ok": present,
            "stage": "wmts_capabilities",
            "service": {
                "provider": "NASA Moon Trek",
                "protocol": "OGC WMTS REST",
                "projection": "lunar equirectangular",
            },
            "layers": [
                {
                    "capability": "moon_lro_wac_global",
                    "expected_layer": _LAYER_ID,
                    "present": present,
                    "coverage": "Mond · global",
                    "source_class": "reference_imagery",
                }
            ],
            "missing_capabilities": [] if present else ["moon_lro_wac_global"],
        }

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        if capability_id != "moon_lro_wac_global":
            raise ValueError(f"Unsupported NASA Moon capability: {capability_id}")

        return {
            "provider": self.id,
            "provider_name": self.name,
            "capability": capability_id,
            "capability_name": "Moon Trek · LRO WAC Global",
            "source_class": "reference_imagery",
            "render_mode": "planetary_tile",
            "attribution": "NASA/JPL Moon Trek · LRO WAC",
            "network_hosts": ["trek.nasa.gov"],
            "provider_metadata": {
                "body": "Moon",
                "layer_id": _LAYER_ID,
                "coverage": "Mond · global",
                "projection": "equirectangular",
            },
            "planetary": {
                "body": "moon",
                "projection": "equirectangular",
                "tile_url_template": _TILE_TEMPLATE,
                "tile_size": 256,
                "min_zoom": 0,
                "max_zoom": 8,
                "initial_zoom": 1,
                "columns_at_zoom0": 2,
                "rows_at_zoom0": 1,
                "extent": {
                    "west": -180.0,
                    "south": -90.0,
                    "east": 180.0,
                    "north": 90.0,
                },
            },
        }
