"""NASA ISS live Earth-view provider for WeatherRouter."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_SOURCE_PAGE = "https://eol.jsc.nasa.gov/esrs/HDEV/"
_USER_AGENT = "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)"
_YOUTUBE_EMBED_RE = re.compile(
    r"https://(?:www\.)?youtube\.com/embed/(?P<video>[A-Za-z0-9_-]{6,})"
)

_CAPABILITIES = (
    CapabilityInfo(
        id="iss_earth_live",
        name="ISS · Live-Erdansicht",
        unit=None,
        source_class="observation",
        render_mode="live_stream",
        description=(
            "Livevideo der Erde von einer externen HD-Kamera an der Internationalen Raumstation."
        ),
        coverage="Erdansicht aus der ISS-Umlaufbahn",
        temporal_resolution="Livevideo bei bestehender Verbindung",
        typical_latency="Livestream",
        strengths=(
            "offizielle NASA/JSC-Quelle",
            "echter Blick auf die Erde aus dem Orbit",
            "NASA-Quellseite bestimmt den aktuell eingebetteten Stream",
        ),
        limitations=(
            "Video kann während Signalunterbrechungen schwarz oder grau sein",
            "historisches HDEV-Experiment endete 2019; heutiger Stream nutzt eine andere externe ISS-Kamera",
            "Wiedergabe hängt zusätzlich von YouTube-Erreichbarkeit ab",
        ),
        documentation_url=_SOURCE_PAGE,
    ),
)


class NasaIssProvider:
    """Resolve NASA's current official ISS Earth-view embed dynamically."""

    id = "nasa_iss"
    name = "NASA · ISS Live"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "NASA/JSC stellt weiterhin Livevideo der Erde von einer externen HD-Kamera "
                "an der Internationalen Raumstation bereit. WeatherRouter liest die offizielle "
                "NASA-HDEV-Seite und übernimmt die dort aktuell verwendete Stream-ID."
            ),
            coverage="Erdansicht aus der ISS-Umlaufbahn",
            strengths=(
                "offizielle NASA/JSC-Quellseite",
                "dynamische Auflösung des aktuell eingebetteten Streams",
                "keine fest verdrahtete YouTube-Video-ID",
            ),
            limitations=(
                "Signalunterbrechungen sind normal",
                "YouTube muss im Browser erreichbar sein",
                "kein georeferenzierter Kartenlayer",
            ),
            documentation_url=_SOURCE_PAGE,
            attribution="NASA / Johnson Space Center · International Space Station",
            services=(
                {
                    "name": "ISS External HD Camera · Earth View",
                    "status": "integriert",
                    "note": "Liveansicht; Stream-ID wird aus der offiziellen NASA-Seite ermittelt",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="iss_live_stream_discovery",
                scheme="https",
                host="eol.jsc.nasa.gov",
                port=443,
                target_type="web",
                required=True,
                capabilities=("iss_earth_live",),
                note="Offizielle NASA/JSC-Seite zur Auflösung des aktuellen ISS-Livestreams.",
            ),
            NetworkTargetInfo(
                purpose="iss_live_stream_playback",
                scheme="https",
                host="www.youtube-nocookie.com",
                port=443,
                target_type="frontend_embed",
                required=True,
                capabilities=("iss_earth_live",),
                note="Datenschutzfreundlicher YouTube-Embed für den von NASA ausgewählten Stream.",
            ),
        )

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        if capability_id != "iss_earth_live":
            raise ValueError(f"Unsupported NASA ISS capability: {capability_id}")

        session = async_get_clientsession(hass)
        async with session.get(
            _SOURCE_PAGE,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=20,
        ) as response:
            response.raise_for_status()
            html = await response.text()

        match = _YOUTUBE_EMBED_RE.search(html)
        if match is None:
            raise ValueError("NASA ISS source page contains no supported YouTube embed")

        video_id = match.group("video")
        embed_url = (
            f"https://www.youtube-nocookie.com/embed/{video_id}"
            "?autoplay=1&mute=1&playsinline=1&rel=0"
        )

        return {
            "provider": self.id,
            "provider_name": self.name,
            "capability": capability_id,
            "capability_name": "ISS · Live-Erdansicht",
            "source_class": "observation",
            "render_mode": "live_stream",
            "attribution": "NASA / Johnson Space Center · International Space Station",
            "network_hosts": [
                "eol.jsc.nasa.gov",
                "www.youtube-nocookie.com",
            ],
            "provider_metadata": {
                "source_page": _SOURCE_PAGE,
                "stream_provider": "YouTube",
                "video_id": video_id,
                "coverage": "Erdansicht aus der ISS-Umlaufbahn",
            },
            "stream": {
                "kind": "iframe",
                "embed_url": embed_url,
                "allow": "autoplay; encrypted-media; picture-in-picture; fullscreen",
                "title": "NASA ISS Live-Erdansicht",
            },
        }
