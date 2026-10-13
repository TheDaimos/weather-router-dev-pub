"""BBK/NINA MoWaS civil-protection warning provider."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .bbk_warning_common import fetch_bbk_feed

_PROVIDER_REVISION = "wr-0.10.48-bbk-mowas-1"
_CAPABILITY_ID = "civil_protection_warnings_germany"

_CAPABILITIES = (
    CapabilityInfo(
        id=_CAPABILITY_ID,
        name="Bevölkerungsschutz Deutschland · MoWaS/NINA",
        unit=None,
        source_class="official_warning",
        render_mode="hazard_feed",
        description=(
            "Aktuelle amtliche Warnmeldungen des Zivil- und Katastrophenschutzes "
            "aus dem Modularen Warnsystem des Bundes."
        ),
        coverage="Deutschland",
        temporal_resolution="laufend aktualisierte Warnlage",
        strengths=(
            "amtliche Warnmeldungen von Bund, Ländern und Kommunen",
            "Warnungen zu Feuer, Infrastruktur, öffentlicher Sicherheit und CBRN-Lagen möglich",
            "öffentliche GeoJSON-Geometrien werden soweit verfügbar übernommen",
        ),
        limitations=(
            "nicht jedes lokale Ereignis löst zwingend eine MoWaS/NINA-Warnung aus",
            "Anweisungen der örtlich zuständigen Stellen haben Vorrang",
            "WeatherRouter verändert oder verschärft die amtliche Aussage nicht",
        ),
        documentation_url="https://www.bbk.bund.de/DE/Warnung-Vorsorge/Warnung-in-Deutschland/MoWaS/mowas_node.html",
    ),
)


class BbkMowasProvider:
    """Expose current official MoWaS warnings from warnung.bund.de."""

    id = "bbk_mowas"
    name = "BBK / NINA · Bevölkerungsschutz"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "MoWaS ist das Modulare Warnsystem des Bundes. WeatherRouter übernimmt "
                "ausschließlich aktuell veröffentlichte Warnmeldungen von warnung.bund.de."
            ),
            coverage="Deutschland",
            strengths=(
                "amtliche Bevölkerungsschutzquelle",
                "mehrere Gefahrenarten statt reiner Wetterwarnungen",
                "GeoJSON-Flächen soweit die Meldung räumliche Daten bereitstellt",
            ),
            limitations=(
                "keine Vollständigkeitsgarantie für jedes lokale Ereignis",
                "kein Ersatz für Cell Broadcast, Sirenen oder örtliche Einsatzkräfte",
            ),
            documentation_url="https://warnung.bund.de/",
            attribution="BBK · warnung.bund.de / NINA / MoWaS",
            services=(
                {
                    "name": "MoWaS mapData + Warning GeoJSON",
                    "status": "integriert",
                    "note": "expliziter On-Demand-Abruf; keine Hintergrundabfrage",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="germany_civil_protection_warnings",
                scheme="https",
                host="warnung.bund.de",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=(_CAPABILITY_ID,),
                note="Amtliche MoWaS/NINA-Warnübersicht und öffentliche Warngeometrien.",
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
            raise ValueError(f"Unsupported BBK MoWaS capability: {capability_id}")
        return await fetch_bbk_feed(
            hass,
            map_path="/mowas/mapData.json",
            provider_id=self.id,
            provider_name=self.name,
            provider_revision=_PROVIDER_REVISION,
            capability_id=capability_id,
            channel="mowas",
            event_label="Civil protection warning",
            bbox=bbox,
            limit=limit,
        )

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id not in {None, _CAPABILITY_ID}:
            return {"ok": False, "stage": "capability_selection"}
        feed = await self.async_get_hazard_feed(hass, _CAPABILITY_ID, limit=25)
        return {
            "ok": True,
            "stage": "bbk_mowas_mapdata_geojson",
            "provider_revision": _PROVIDER_REVISION,
            "event_count": feed.get("event_count", 0),
            "metadata": feed.get("provider_metadata"),
        }
