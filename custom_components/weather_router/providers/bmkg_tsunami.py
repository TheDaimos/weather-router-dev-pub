"""BMKG earthquake tsunami-potential indicator provider."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import tsunami_semantics

_API = "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json"
_PROVIDER_REVISION = "wr-0.10.129-tsunami-semantics-1"

_CAPABILITIES = (
    CapabilityInfo(
        id="tsunami_potential_earthquake",
        name="Erdbeben mit Tsunamipotenzial · BMKG",
        unit=None,
        source_class="event_indicator",
        render_mode="hazard_feed",
        description=(
            "Offener BMKG-Erdbebendatensatz. WeatherRouter erzeugt nur dann einen "
            "tsunami_potential-Indikator, wenn BMKG das jüngste Erdbeben ausdrücklich "
            "als tsunamirelevant kennzeichnet."
        ),
        coverage="Indonesien / BMKG-Erdbebendienst",
        temporal_resolution="ereignisgesteuert",
        strengths=(
            "amtliche BMKG-Quelle",
            "Epizentrum, Magnitude, Tiefe und Potenzialtext",
            "schlüsselloser JSON-Zugriff",
        ),
        limitations=(
            "Tsunamipotenzial ist keine Tsunamiwarnung",
            "für amtliche Warnstufen/Handlungsanweisungen sind InaTEWS- bzw. nationale "
            "Tsunamiwarnmeldungen maßgeblich",
        ),
        documentation_url="https://data.bmkg.go.id/gempabumi/",
    ),
)


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _depth_km(value: Any) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else None


def _coordinates(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, str):
        return None
    parts = [item.strip() for item in value.split(",")]
    if len(parts) != 2:
        return None
    try:
        latitude = float(parts[0])
        longitude = float(parts[1])
    except ValueError:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def _has_tsunami_potential(value: Any) -> bool:
    text = str(value or "").casefold()
    if "tsunami" not in text:
        return False
    negatives = (
        "tidak berpotensi tsunami",
        "tidak berpotensi menimbulkan tsunami",
        "no tsunami",
        "not potential",
    )
    if any(item in text for item in negatives):
        return False
    return "berpotensi" in text or "potential" in text or "tsunami" in text


class BmkgTsunamiProvider:
    """Expose BMKG's explicit tsunami-potential earthquake indicator."""

    id = "bmkg_tsunami"
    name = "BMKG · Indonesia Tsunami / Earthquake"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "BMKG veröffentlicht offene aktuelle Erdbebendaten einschließlich eines "
                "Potenzialfelds für Tsunamirelevanz. WeatherRouter behandelt dies bewusst "
                "nur als Vorläufer/Indikator und nicht als amtliche Tsunamiwarnung."
            ),
            coverage="Indonesien / BMKG",
            strengths=(
                "amtliche indonesische Quelle",
                "offene JSON-Daten",
                "explizite BMKG-Potenzialaussage",
            ),
            limitations=(
                "nur jüngstes Erdbeben im verwendeten Open-Data-Endpunkt",
                "kein Ersatz für InaTEWS-/nationale Warnbulletins",
            ),
            documentation_url="https://data.bmkg.go.id/gempabumi/",
            attribution="BMKG · Badan Meteorologi, Klimatologi, dan Geofisika",
            services=(
                {
                    "name": "BMKG Open Earthquake Data",
                    "status": "integriert",
                    "note": "Tsunamipotenzial als eigener event_indicator",
                },
                {
                    "name": "InaTEWS",
                    "status": "katalogisiert",
                    "note": (
                        "amtliche Tsunamibulletins vorhanden; kein unbestätigtes "
                        "Web-Scraping als API-Ersatz"
                    ),
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="tsunami_potential_earthquake",
                scheme="https",
                host="data.bmkg.go.id",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=("tsunami_potential_earthquake",),
                note=(
                    "BMKG Open Data autogempa.json; documented 60 requests/minute/IP "
                    "limit and mandatory BMKG attribution."
                ),
            ),
        )

    async def _async_latest(self, hass: HomeAssistant) -> dict[str, Any]:
        session = async_get_clientsession(hass)
        async with session.get(
            _API,
            headers={"Accept": "application/json"},
            timeout=20,
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)

        info = payload.get("Infogempa")
        quake = info.get("gempa") if isinstance(info, dict) else None
        if not isinstance(quake, dict):
            raise ValueError("BMKG autogempa response has no Infogempa.gempa object")
        return quake

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
        del latitude, longitude, bbox, limit
        if capability_id != "tsunami_potential_earthquake":
            raise ValueError(f"Unsupported BMKG tsunami capability: {capability_id}")

        quake = await self._async_latest(hass)
        coordinate = _coordinates(quake.get("Coordinates"))
        potential_text = str(quake.get("Potensi") or "")
        potential = _has_tsunami_potential(potential_text)
        magnitude = _float_value(quake.get("Magnitude"))
        depth = _depth_km(quake.get("Kedalaman"))
        event_time = quake.get("DateTime")

        event: dict[str, Any] | None = None
        if potential:
            geometry = (
                {
                    "type": "Point",
                    "coordinates": [coordinate[1], coordinate[0]],
                }
                if coordinate is not None
                else None
            )
            event = {
                "id": f"bmkg:{event_time or quake.get('Shakemap') or 'latest'}",
                "hazard_type": "tsunami_potential",
                "tsunami_semantics": tsunami_semantics(
                    "tsunami_potential_indicator_event",
                    wave_evidence="none",
                ),
                "event": "Tsunami Potential Earthquake",
                "headline": "BMKG · Erdbeben mit Tsunamipotenzial",
                "severity": "unknown",
                "urgency": "immediate",
                "certainty": "possible",
                "status": "actual",
                "message_type": "alert",
                "sent": event_time,
                "effective": event_time,
                "onset": event_time,
                "expires": None,
                "ends": None,
                "area_desc": quake.get("Wilayah"),
                # Triggering earthquake epicenter is not a Tsunami impact/warning area.
                "geometry": None,
                "description": potential_text,
                "instruction": (
                    "Dieser WeatherRouter-Eintrag ist nur ein BMKG-Potenzialindikator. "
                    "Für Warnstatus und Maßnahmen sind amtliche Tsunamiwarnungen maßgeblich."
                ),
                "sender_name": "BMKG",
                "response": "monitor",
                "affected_zones": [],
                "parameters": {
                    "alert_level": "potential",
                    "earthquake_epicenter": geometry,
                    "magnitude": magnitude,
                    "depth_km": depth,
                    "latitude_text": quake.get("Lintang"),
                    "longitude_text": quake.get("Bujur"),
                    "potential_text": potential_text,
                    "felt": quake.get("Dirasakan"),
                    "shakemap": quake.get("Shakemap"),
                },
                "web_url": "https://inatews.bmkg.go.id/",
            }

        events = [event] if event is not None else []
        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "event_indicator",
            "render_mode": "hazard_feed",
            "coverage_status": "regional",
            "events": events,
            "event_count": len(events),
            "provider_metadata": {
                "latest_earthquake": {
                    "datetime": event_time,
                    "magnitude": magnitude,
                    "depth_km": depth,
                    "region": quake.get("Wilayah"),
                    "potential_text": potential_text,
                    "tsunami_potential": potential,
                },
                "semantic_boundary": (
                    "tsunami_potential is not an official tsunami warning"
                ),
            },
            "attribution": "BMKG · Badan Meteorologi, Klimatologi, dan Geofisika",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id not in {None, "tsunami_potential_earthquake"}:
            return {
                "ok": False,
                "stage": "capability_selection",
                "provider_revision": _PROVIDER_REVISION,
            }
        feed = await self.async_get_hazard_feed(
            hass,
            "tsunami_potential_earthquake",
        )
        return {
            "ok": True,
            "stage": "bmkg_open_earthquake_data",
            "provider_revision": _PROVIDER_REVISION,
            "event_count": feed.get("event_count", 0),
            "latest_earthquake": (feed.get("provider_metadata") or {}).get(
                "latest_earthquake"
            ),
            "semantic_boundary": (
                "Potential indicator only; not promoted to tsunami warning."
            ),
        }
