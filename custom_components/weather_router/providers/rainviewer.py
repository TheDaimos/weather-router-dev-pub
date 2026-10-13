"""RainViewer radar map-layer provider for WeatherRouter V0.10 TEST."""

from __future__ import annotations

from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_METADATA_URL = "https://api.rainviewer.com/public/weather-maps.json"
_CACHE_TTL_SECONDS = 120.0

_CAPABILITIES = (
    CapabilityInfo(
        "radar_reflectivity",
        "Niederschlagsradar",
        None,
        "observation",
        "raster_tile",
    ),
)

_cached_payload: dict[str, Any] | None = None
_cache_valid_until = 0.0


async def _async_weather_maps(hass: HomeAssistant) -> dict[str, Any]:
    """Fetch and briefly cache the RainViewer weather-map metadata."""
    global _cached_payload, _cache_valid_until

    now = monotonic()
    if _cached_payload is not None and now < _cache_valid_until:
        return _cached_payload

    session = async_get_clientsession(hass)
    async with session.get(_METADATA_URL, timeout=15) as response:
        response.raise_for_status()
        payload = await response.json()

    if not isinstance(payload, dict):
        raise ValueError("RainViewer metadata is not an object")

    _cached_payload = payload
    _cache_valid_until = now + _CACHE_TTL_SECONDS
    return payload


def _validated_frames(host: str, raw_frames: Any) -> list[dict[str, Any]]:
    """Return valid historical radar frames as generic raster-frame descriptors."""
    if not isinstance(raw_frames, list):
        return []

    result: list[dict[str, Any]] = []
    for raw in raw_frames:
        if not isinstance(raw, dict):
            continue
        frame_time = raw.get("time")
        path = raw.get("path")
        if (
            not isinstance(frame_time, int)
            or not isinstance(path, str)
            or not path.startswith("/")
        ):
            continue
        result.append(
            {
                "time": frame_time,
                "tile_url": f"{host}{path}/256/{{z}}/{{x}}/{{y}}/2/1_1.png",
                "kind": "observation",
            }
        )

    result.sort(key=lambda item: item["time"])
    return result


class RainViewerProvider:
    """RainViewer observed-radar tile adapter."""

    id = "rainviewer"
    name = "RainViewer"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        """Return implemented RainViewer capabilities."""
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        """Return explanatory metadata for the generic provider info UI."""
        return ProviderInfo(
            summary=(
                "RainViewer stellt beobachtungsbasierte Niederschlagsradar-Karten aus "
                "verfügbaren Wetterradarnetzen als kachelbare Zeitleiste bereit."
            ),
            coverage="International, abhängig von vorhandener Radarversorgung",
            strengths=(
                "beobachtungsbasierte Radarbilder",
                "direkt kachelbarer Kartenlayer",
                "historische Radarframes für Animationen",
            ),
            limitations=(
                "Abdeckung und Aktualität hängen von regionalen Radarnetzen ab",
                "dynamischer Tile-Host wird über Metadaten aufgelöst",
            ),
            documentation_url="https://www.rainviewer.com/api.html",
            attribution="RainViewer",
            services=(
                {"name": "Weather Maps / Radar", "status": "integriert", "note": "Radarreflektivität"},
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        """Return the stable metadata endpoint used before resolving tile hosts."""
        return (
            NetworkTargetInfo(
                purpose="weather_map_metadata",
                scheme="https",
                host="api.rainviewer.com",
                port=443,
                target_type="metadata",
                required=True,
                capabilities=("radar_reflectivity",),
                note=(
                    "Der konkrete Radar-Tile-Host wird dynamisch aus weather-maps.json "
                    "ermittelt und im Laufzeit-Layerdescriptor ausgewiesen."
                ),
            ),
        )

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Return observed radar frames as a generic MapLibre raster-layer descriptor."""
        if capability_id != "radar_reflectivity":
            raise ValueError(f"Unsupported RainViewer map capability: {capability_id}")

        payload = await _async_weather_maps(hass)
        host = payload.get("host")
        radar = payload.get("radar")
        raw_frames = radar.get("past") if isinstance(radar, dict) else None

        if not isinstance(host, str) or not host.startswith("https://"):
            raise ValueError("RainViewer metadata returned an invalid HTTPS host")

        host = host.rstrip("/")
        frames = _validated_frames(host, raw_frames)
        if not frames:
            raise ValueError("RainViewer metadata contains no valid past radar frames")

        latest = frames[-1]
        tile_host = urlsplit(host).hostname

        return {
            "provider": self.id,
            "provider_name": self.name,
            "capability": capability_id,
            "source_class": "observation",
            "render_mode": "raster_tile",
            "frame_time": latest["time"],
            "generated": payload.get("generated"),
            "tile_url": latest["tile_url"],
            "tile_size": 256,
            "max_zoom": 7,
            "default_opacity": 0.65,
            "timeline": {
                "mode": "frames",
                "default": "latest",
                "loop": True,
                "frames": frames,
            },
            "attribution": (
                'Weather radar by <a href="https://www.rainviewer.com/" '
                'target="_blank" rel="noopener noreferrer">RainViewer</a>'
            ),
            "network_hosts": [
                "api.rainviewer.com",
                *([tile_host] if tile_host else []),
            ],
        }
