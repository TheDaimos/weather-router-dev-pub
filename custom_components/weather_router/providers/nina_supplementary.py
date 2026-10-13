"""Supplementary warnung.bund.de / NINA public warning channels."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .bbk_warning_common import fetch_bbk_feed
from .hazard_common import flood_semantics


class _NinaChannelProvider:
    id = ""
    name = ""
    revision = "wr-0.10.48-nina-supplementary-1"
    capability_id = ""
    capability_name = ""
    map_path = ""
    channel = ""
    coverage = "Deutschland"
    summary = ""
    source_class = "official_warning"
    event_label = "Civil protection warning"
    documentation_url = "https://warnung.bund.de/"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return (
            CapabilityInfo(
                id=self.capability_id,
                name=self.capability_name,
                unit=None,
                source_class=self.source_class,
                render_mode="hazard_feed",
                description=self.summary,
                coverage=self.coverage,
                temporal_resolution="laufend aktualisierte öffentliche Warnlage",
                strengths=(
                    "öffentliche Warnquelle über warnung.bund.de",
                    "GeoJSON-Geometrien soweit für die Meldung verfügbar",
                    "expliziter On-Demand-Abruf ohne Hintergrundpolling",
                ),
                limitations=(
                    "kann sich mit anderen Warnkanälen inhaltlich überschneiden",
                    "WeatherRouter erhält die Quellaussage und erfindet keine stärkere Semantik",
                ),
                documentation_url=self.documentation_url,
            ),
        )

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=self.summary,
            coverage=self.coverage,
            strengths=(
                "öffentliche Warnquelle über warnung.bund.de",
                "kartierbare Warngeometrien soweit vorhanden",
            ),
            limitations=(
                "optionaler Ergänzungskanal; Überschneidungen mit MoWaS sind möglich",
                "keine automatische Aktivierung bei bestehenden Installationen",
            ),
            documentation_url=self.documentation_url,
            attribution="warnung.bund.de / NINA",
            services=(
                {
                    "name": self.capability_name,
                    "status": "integriert",
                    "note": "optional; expliziter On-Demand-Abruf",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose=f"{self.channel}_public_warnings",
                scheme="https",
                host="warnung.bund.de",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=(self.capability_id,),
                note=f"warnung.bund.de API31 · {self.channel} mapData + GeoJSON.",
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
        if capability_id != self.capability_id:
            raise ValueError(
                f"Unsupported {self.name} capability: {capability_id}"
            )
        return await fetch_bbk_feed(
            hass,
            map_path=self.map_path,
            provider_id=self.id,
            provider_name=self.name,
            provider_revision=self.revision,
            capability_id=capability_id,
            channel=self.channel,
            event_label=self.event_label,
            source_semantics=self.source_class,
            bbox=bbox,
            limit=limit,
        )

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id not in {None, self.capability_id}:
            return {"ok": False, "stage": "capability_selection"}
        feed = await self.async_get_hazard_feed(
            hass,
            self.capability_id,
            limit=25,
        )
        return {
            "ok": True,
            "stage": f"nina_{self.channel}_mapdata_geojson",
            "provider_revision": self.revision,
            "event_count": feed.get("event_count", 0),
            "metadata": feed.get("provider_metadata"),
        }


class NinaFloodProvider(_NinaChannelProvider):
    """Länderübergreifendes Hochwasserportal as a NINA warning channel."""

    id = "nina_flood"
    revision = "wr-0.10.126-flood-semantics-1"
    name = "NINA / LHP · Hochwasser"
    capability_id = "flood_information_germany"
    capability_name = "Hochwasserinformationen Deutschland · LHP/NINA"
    map_path = "/lhp/mapData.json"
    channel = "lhp"
    source_class = "official_warning"
    event_label = "Flood information"
    summary = (
        "Hochwasserinformationen der zuständigen Stellen der Bundesländer, "
        "bereitgestellt über den öffentlichen warnung.bund.de/NINA-Datenweg."
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
        """Return NINA/LHP flood warnings with semantics from real headline text."""
        feed = await super().async_get_hazard_feed(
            hass,
            capability_id,
            latitude=latitude,
            longitude=longitude,
            bbox=bbox,
            limit=limit,
        )
        for event in feed.get("events", []):
            if not isinstance(event, dict):
                continue
            semantics = flood_semantics(headline=event.get("headline"))
            if semantics:
                event["flood_semantics"] = semantics
        return feed


class NinaKatwarnProvider(_NinaChannelProvider):
    """KATWARN messages exposed through warnung.bund.de."""

    id = "nina_katwarn"
    name = "NINA · KATWARN"
    capability_id = "katwarn_public_warnings"
    capability_name = "KATWARN-Meldungen · NINA"
    map_path = "/katwarn/mapData.json"
    channel = "katwarn"
    event_label = "Public warning"
    summary = (
        "Öffentliche KATWARN-Meldungen, soweit sie über den "
        "warnung.bund.de/NINA-Datenweg bereitgestellt werden."
    )


class NinaBiwappProvider(_NinaChannelProvider):
    """BIWAPP messages exposed through warnung.bund.de."""

    id = "nina_biwapp"
    name = "NINA · BIWAPP"
    capability_id = "biwapp_public_warnings"
    capability_name = "BIWAPP-Meldungen · NINA"
    map_path = "/biwapp/mapData.json"
    channel = "biwapp"
    event_label = "Public warning"
    summary = (
        "Öffentliche BIWAPP-Meldungen, soweit sie über den "
        "warnung.bund.de/NINA-Datenweg bereitgestellt werden."
    )
