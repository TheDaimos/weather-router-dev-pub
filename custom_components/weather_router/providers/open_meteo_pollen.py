"""Open-Meteo / CAMS pollen forecast provider for WeatherRouter."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_API_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

_FIELDS = {
    "alder_pollen": "alder_pollen",
    "birch_pollen": "birch_pollen",
    "grass_pollen": "grass_pollen",
    "mugwort_pollen": "mugwort_pollen",
    "olive_pollen": "olive_pollen",
    "ragweed_pollen": "ragweed_pollen",
}

_NAMES = {
    "alder_pollen": "Erlenpollen",
    "birch_pollen": "Birkenpollen",
    "grass_pollen": "Gräserpollen",
    "mugwort_pollen": "Beifußpollen",
    "olive_pollen": "Olivenpollen",
    "ragweed_pollen": "Ambrosiapollen",
}

_CAPABILITIES = tuple(
    CapabilityInfo(
        capability_id,
        _NAMES[capability_id],
        "Grains/m³",
        "forecast",
        "value",
        f"Modellierte Konzentration von {_NAMES[capability_id]} aus CAMS Europe.",
        "Europa · CAMS European Air Quality Forecast",
        "stündlich · bis 4 Tage",
        None,
        (
            "schlüsselloser Zugriff über Open-Meteo",
            "CAMS-Europe-Pollenmodell mit stündlicher Auflösung",
        ),
        (
            "nur Europa und nur während der Pollensaison",
            "Konzentration ist keine personalisierte medizinische Warnung",
            "universelle medizinische Schwellenwerte werden nicht erfunden",
        ),
        "https://open-meteo.com/en/docs/air-quality-api",
    )
    for capability_id in _FIELDS
)


class OpenMeteoPollenProvider:
    """European pollen concentrations from Open-Meteo backed by CAMS Europe."""

    id = "open_meteo_pollen"
    name = "Open-Meteo · Pollen"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Open-Meteo stellt Pollenprognosen aus dem Copernicus Atmosphere "
                "Monitoring Service (CAMS Europe) bereit."
            ),
            coverage="Europa · Pollensaison",
            strengths=(
                "Erle, Birke, Gräser, Beifuß, Olive und Ambrosia",
                "stündliche Konzentrationen",
                "bis zu 4 Tage Pollenprognose",
                "kein API-Schlüssel erforderlich",
            ),
            limitations=(
                "Pollenvariablen sind laut Quelle nur in Europa verfügbar",
                "keine weltweite Pollenabdeckung",
                "keine personalisierte medizinische Empfehlung",
                "keine selbst erfundenen Allergie-Warnschwellen",
            ),
            documentation_url="https://open-meteo.com/en/docs/air-quality-api",
            attribution="Open-Meteo · CAMS European Air Quality Forecast",
            services=(
                {"name": "CAMS Europe Pollen", "status": "integriert", "note": "Erle, Birke, Gräser, Beifuß, Olive, Ambrosia"},
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="pollen_forecast",
                scheme="https",
                host="air-quality-api.open-meteo.com",
                port=443,
                target_type="api",
                required=True,
                capabilities=tuple(_FIELDS),
                note="Open-Meteo Air Quality API · CAMS-Europe-Pollen.",
            ),
        )

    async def async_fetch_point(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        capability_ids: list[str],
    ) -> dict[str, Any]:
        requested = list(dict.fromkeys(item for item in capability_ids if item in _FIELDS))
        if not requested:
            return {
                "provider": self.id,
                "provider_name": self.name,
                "source_class": "forecast",
                "values": {},
            }

        fields = sorted({_FIELDS[item] for item in requested})
        session = async_get_clientsession(hass)
        async with session.get(
            _API_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": ",".join(fields),
                "hourly": ",".join(fields),
                "past_hours": 1,
                "forecast_hours": 2,
                "timezone": "auto",
                "domains": "cams_europe",
            },
            timeout=15,
        ) as response:
            if response.status == 400:
                try:
                    error_payload = await response.json()
                except Exception:  # noqa: BLE001
                    error_payload = {}
                reason = str(error_payload.get("reason") or "Pollen außerhalb der verfügbaren Abdeckung.")
                return {
                    "provider": self.id,
                    "provider_name": self.name,
                    "source_class": "forecast",
                    "coverage_status": "outside_coverage",
                    "reason": reason,
                    "values": {},
                }
            response.raise_for_status()
            payload = await response.json()

        from ..time_normalization import provider_local_instant
        zone = payload.get("timezone")
        normalized_current = (
            provider_local_instant(payload.get("current", {}).get("time"), iana_zone=zone)
            if isinstance(zone, str) else None)
        current = payload.get("current", {})
        current_units = payload.get("current_units", {})
        hourly = payload.get("hourly", {})
        hourly_units = payload.get("hourly_units", {})

        def nearest_hourly(field: str) -> Any:
            values = hourly.get(field)
            if not isinstance(values, list) or not values:
                return None
            return values[0]

        values: dict[str, Any] = {}
        for capability_id in requested:
            field = _FIELDS[capability_id]
            value = current.get(field)
            unit = current_units.get(field)
            source = "current"
            if value is None:
                value = nearest_hourly(field)
                unit = hourly_units.get(field, unit)
                source = "hourly_nearest"
            values[capability_id] = {
                "value": value,
                "unit": unit or "Grains/m³",
                "field": field,
                "time_source": source,
            }

        return {
            "provider": self.id,
            "provider_name": self.name,
            "source_class": "forecast",
            "latitude": payload.get("latitude", latitude),
            "longitude": payload.get("longitude", longitude),
            "timezone": payload.get("timezone"),
            "data_time": normalized_current,
            "source_local_time": current.get("time"),
            "time_zone_origin": "provider_iana" if normalized_current else "unknown_time_zone",
            "coverage_status": "inside_coverage",
            "values": values,
            "attribution": "Open-Meteo · CAMS European Air Quality Forecast",
        }
