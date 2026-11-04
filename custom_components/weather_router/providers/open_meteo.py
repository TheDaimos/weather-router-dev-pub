"""Open-Meteo diagnostic point provider for WeatherRouter V0.10 TEST."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_API_URL = "https://api.open-meteo.com/v1/forecast"

_CAPABILITIES = (
    CapabilityInfo("temperature", "Temperatur", "°C", "model"),
    CapabilityInfo("cloud_cover", "Wolken gesamt", "%", "model"),
    CapabilityInfo("cloud_cover_low", "Tiefe Wolken / Nebel", "%", "model"),
    CapabilityInfo("cloud_cover_mid", "Mittlere Wolken", "%", "model"),
    CapabilityInfo("cloud_cover_high", "Hohe Wolken", "%", "model"),
    CapabilityInfo("precipitation", "Niederschlag", "mm", "model"),
    CapabilityInfo("rain", "Regen", "mm", "model"),
    CapabilityInfo("showers", "Schauer", "mm", "model"),
    CapabilityInfo("snowfall", "Schneefall", "cm", "model"),
    CapabilityInfo("wind_speed", "Windgeschwindigkeit 10 m", "km/h", "model"),
    CapabilityInfo("wind_direction", "Windrichtung 10 m", "°", "model"),
    CapabilityInfo("wind_gusts", "Windböen 10 m", "km/h", "model"),
    CapabilityInfo("visibility", "Sichtweite", "m", "model"),
    CapabilityInfo("uv_index", "UV-Index", "1", "model"),
    CapabilityInfo("uv_index_clear_sky", "UV-Index · klarer Himmel", "1", "model"),
    CapabilityInfo("uv_index_max_today", "UV-Index · Tagesmaximum", "1", "model"),
    CapabilityInfo("uv_index_clear_sky_max_today", "UV-Index · Tagesmaximum klarer Himmel", "1", "model"),
    CapabilityInfo("weather_code", "WMO-Wettercode", None, "model"),
)
_CAPABILITY_MAP = {item.id: item for item in _CAPABILITIES}

_API_FIELDS = {
    "temperature": "temperature_2m",
    "cloud_cover": "cloud_cover",
    "cloud_cover_low": "cloud_cover_low",
    "cloud_cover_mid": "cloud_cover_mid",
    "cloud_cover_high": "cloud_cover_high",
    "precipitation": "precipitation",
    "rain": "rain",
    "showers": "showers",
    "snowfall": "snowfall",
    "wind_speed": "wind_speed_10m",
    "wind_direction": "wind_direction_10m",
    "wind_gusts": "wind_gusts_10m",
    "visibility": "visibility",
    "uv_index": "uv_index",
    "uv_index_clear_sky": "uv_index_clear_sky",
    "weather_code": "weather_code",
}

_DAILY_API_FIELDS = {
    "uv_index_max_today": "uv_index_max",
    "uv_index_clear_sky_max_today": "uv_index_clear_sky_max",
}


class OpenMeteoProvider:
    """Open-Meteo point-data adapter."""

    id = "open_meteo"
    name = "Open-Meteo"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        """Return implemented Open-Meteo capabilities."""
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        """Return explanatory metadata for the generic provider info UI."""
        return ProviderInfo(
            summary=(
                "Open-Meteo stellt schlüssellose Wettermodell-Punktdaten über eine "
                "einheitliche Forecast-API bereit."
            ),
            coverage="Global",
            strengths=(
                "schlüsselloser Zugriff",
                "breite Auswahl an Wetterparametern",
                "UV-Index und Clear-Sky-UV als getrennte Größen",
                "einfacher globaler Vergleichsprovider",
            ),
            limitations=(
                "Modellwerte sind keine direkten Messungen",
                "verfügbare Modelle und Auflösung unterscheiden sich regional",
            ),
            documentation_url="https://open-meteo.com/en/docs",
            attribution="Weather data by Open-Meteo.com",
            services=(
                {"name": "Forecast API", "status": "integriert", "note": "globale Punktwerte"},
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        """Return documented secret-free network targets."""
        return (
            NetworkTargetInfo(
                purpose="point_weather_api",
                scheme="https",
                host="api.open-meteo.com",
                port=443,
                target_type="api",
                required=True,
                capabilities=tuple(capability.id for capability in _CAPABILITIES),
            ),
        )

    async def async_fetch_point(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        capability_ids: list[str],
    ) -> dict[str, Any]:
        """Fetch current point values in one Open-Meteo request."""
        requested = [
            item for item in capability_ids
            if item in _API_FIELDS or item in _DAILY_API_FIELDS
        ]
        if not requested:
            return {
                "provider": self.id,
                "provider_name": self.name,
                "source_class": "model",
                "values": {},
            }

        current_fields = sorted({
            _API_FIELDS[item]
            for item in requested
            if item in _API_FIELDS
        })
        uv_fields = sorted({
            _API_FIELDS[item]
            for item in requested
            if item in {"uv_index", "uv_index_clear_sky"}
        })
        daily_fields = sorted({
            _DAILY_API_FIELDS[item]
            for item in requested
            if item in _DAILY_API_FIELDS
        })
        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": "auto",
        }
        if current_fields:
            params["current"] = ",".join(current_fields)
        if daily_fields:
            params["daily"] = ",".join(daily_fields)
            params["forecast_days"] = 1
        if uv_fields:
            # UV is documented as a forecast variable; keep a tiny hourly fallback
            # so the provider still resolves UV when it is not emitted in current.
            params["hourly"] = ",".join(uv_fields)
            params["past_hours"] = 1
            params["forecast_hours"] = 2

        session = async_get_clientsession(hass)
        async with session.get(
            _API_URL,
            params=params,
            timeout=15,
        ) as response:
            response.raise_for_status()
            payload = await response.json()

        from ..time_normalization import (
            provider_local_instant, calendar_day_interval,
        )
        reported_zone = payload.get("timezone")
        def local_utc(value):
            return (provider_local_instant(value, iana_zone=reported_zone)
                    if isinstance(reported_zone, str) else None)
        current = payload.get("current", {})
        units = payload.get("current_units", {})
        hourly = payload.get("hourly", {})
        hourly_units = payload.get("hourly_units", {})
        daily = payload.get("daily", {})
        daily_units = payload.get("daily_units", {})

        def nearest_hourly(field: str) -> tuple[Any, str | None]:
            times = hourly.get("time")
            series = hourly.get(field)
            if not isinstance(times, list) or not isinstance(series, list) or not times or not series:
                return None, None
            target_text = current.get("time")
            try:
                target_text_utc = local_utc(target_text)
                if target_text_utc is None:
                    return None, None
                target = datetime.fromisoformat(target_text_utc.replace("Z", "+00:00"))
                candidates = []
                for index, value in enumerate(times[:len(series)]):
                    utc_value = local_utc(value)
                    if utc_value:
                        stamped = datetime.fromisoformat(utc_value.replace("Z", "+00:00"))
                        candidates.append((abs((stamped - target).total_seconds()), index))
                if not candidates:
                    return None, None
                _delta, index = min(candidates)
                return series[index], local_utc(times[index])
            except (TypeError, ValueError):
                return None, None

        values: dict[str, Any] = {}
        all_values_share_current_time = True
        current_utc = local_utc(current.get("time"))
        for capability_id in requested:
            if capability_id in _DAILY_API_FIELDS:
                all_values_share_current_time = False
                field = _DAILY_API_FIELDS[capability_id]
                series = daily.get(field)
                value = series[0] if isinstance(series, list) and series else None
                daily_times = daily.get("time")
                local_day = (
                    daily_times[0]
                    if isinstance(daily_times, list) and daily_times
                    else None
                )
                values[capability_id] = {
                    "value": value,
                    "unit": daily_units.get(field) or _CAPABILITY_MAP[capability_id].unit,
                    "field": field,
                    "time_source": "daily_today",
                    "local_day": local_day,
                    "interval_start": (calendar_day_interval(local_day, iana_zone=reported_zone) or (None, None))[0] if isinstance(reported_zone, str) else None,
                    "interval_end": (calendar_day_interval(local_day, iana_zone=reported_zone) or (None, None))[1] if isinstance(reported_zone, str) else None,
                }
                continue

            field = _API_FIELDS[capability_id]
            value = current.get(field)
            unit = units.get(field)
            source_field = "current"
            valid_at = current_utc
            if value is None and field in uv_fields:
                all_values_share_current_time = False
                value, valid_at = nearest_hourly(field)
                unit = hourly_units.get(field, unit)
                source_field = "hourly_nearest"
            values[capability_id] = {
                "value": value,
                "unit": unit or _CAPABILITY_MAP[capability_id].unit,
                "field": field,
                "time_source": source_field,
                "valid_at": valid_at,
            }

        return {
            "provider": self.id,
            "provider_name": self.name,
            "source_class": "model",
            "latitude": payload.get("latitude", latitude),
            "longitude": payload.get("longitude", longitude),
            "timezone": payload.get("timezone"),
            "data_time": current_utc if all_values_share_current_time else None,
            "source_local_time": current.get("time"),
            "time_zone_origin": "provider_iana" if current_utc else "unknown_time_zone",
            "interval": current.get("interval"),
            "values": values,
            "attribution": "Weather data by Open-Meteo.com",
        }
