"""BBK/NINA official police public-safety warning provider."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .bbk_warning_common import fetch_bbk_feed

_PROVIDER_REVISION = "wr-0.10.48-bbk-police-1"
_CAPABILITY_ID = "police_public_safety_warnings_germany"

_CAPABILITIES = (
    CapabilityInfo(
        id=_CAPABILITY_ID,
        name="Öffentliche Sicherheit Deutschland · Polizeiwarnungen",
        unit=None,
        source_class="official_warning",
        render_mode="hazard_feed",
        description=(
            "Aktuelle polizeiliche Warnmeldungen aus der öffentlichen Warninfrastruktur "
            "von warnung.bund.de."
        ),
        coverage="Deutschland",
        temporal_resolution="laufend aktualisierte Warnlage",
        strengths=(
            "amtliche Quelle",
            "öffentliche Sicherheitslagen werden quellengetreu benannt",
            "öffentliche GeoJSON-Geometrien werden soweit verfügbar übernommen",
        ),
        limitations=(
            "WeatherRouter leitet aus einer Polizeiwarnung niemals selbst einen Anschlag, "
            "Terrorismus oder eine Tatursache ab",
            "nur veröffentlichte Warnmeldungen; kein Einsatz- oder Nachrichtendienst",
        ),
        documentation_url="https://warnung.bund.de/",
    ),
)


class BbkPoliceProvider:
    """Expose current official police warnings without semantic escalation."""

    id = "bbk_police"
    name = "BBK / NINA · Öffentliche Sicherheit"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Der Provider zeigt ausschließlich öffentlich bereitgestellte "
                "Polizeiwarnungen von warnung.bund.de. WeatherRouter übernimmt die "
                "Quellaussage und führt keine eigene Tat- oder Terrorismusklassifikation durch."
            ),
            coverage="Deutschland",
            strengths=(
                "amtliche Warnquelle",
                "geeignet für öffentliche Sicherheitslagen mit Warncharakter",
            ),
            limitations=(
                "kein Polizeiliveticker und kein Nachrichtendienst",
                "keine automatische Interpretation als Anschlag, Krieg oder Terrorismus",
            ),
            documentation_url="https://warnung.bund.de/",
            attribution="BBK · warnung.bund.de / Polizeiwarnungen",
            services=(
                {
                    "name": "Police mapData + Warning GeoJSON",
                    "status": "integriert",
                    "note": "expliziter On-Demand-Abruf; standardmäßig deaktiviert",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="germany_public_safety_warnings",
                scheme="https",
                host="warnung.bund.de",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=(_CAPABILITY_ID,),
                note="Öffentliche polizeiliche Warnmeldungen und Warngeometrien.",
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
            raise ValueError(f"Unsupported BBK police capability: {capability_id}")
        return await fetch_bbk_feed(
            hass,
            map_path="/police/mapData.json",
            provider_id=self.id,
            provider_name=self.name,
            provider_revision=_PROVIDER_REVISION,
            capability_id=capability_id,
            channel="police",
            event_label="Police public-safety warning",
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
            "stage": "bbk_police_mapdata_geojson",
            "provider_revision": _PROVIDER_REVISION,
            "event_count": feed.get("event_count", 0),
            "metadata": feed.get("provider_metadata"),
        }
