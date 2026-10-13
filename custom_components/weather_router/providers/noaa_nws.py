"""NOAA / National Weather Service point forecast provider for WeatherRouter."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import (
    flood_semantics,
    geometry_intersects_bbox_strict,
    hail_hazard_match_scope,
    hail_semantic_class,
    normalize_alert_stage,
    normalize_hazard_type,
    normalize_severity,
    supercell_hazard_match_scope,
    supercell_semantic_class,
    tornado_hazard_match_scope,
    tornado_semantic_class,
    tropical_system_from_explicit_text,
    wind_hazard_match_scope,
    wind_hazard_semantic_class,
)

_API = "https://api.weather.gov"
_USER_AGENT = "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)"
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/geo+json",
}
_FORECAST_HEADERS = {
    **_HEADERS,
    "Feature-Flags": "forecast_temperature_qv,forecast_wind_speed_qv",
}

_COVERAGE = "USA, US-Territorien und ausgewählte Küsten-/Marinegebiete"

_CAPABILITIES = (
    CapabilityInfo(
        id="temperature",
        name="Temperatur",
        unit="°C",
        source_class="forecast",
        description="Stündliche NWS-Punktvorhersage der Lufttemperatur.",
        coverage=_COVERAGE,
        temporal_resolution="stündlich",
        strengths=("offizielle NWS-Vorhersage", "lokale Weather Forecast Offices"),
        limitations=("nur innerhalb des NWS-Abdeckungsgebiets verfügbar",),
        documentation_url="https://www.weather.gov/documentation/services-web-api",
    ),
    CapabilityInfo(
        id="dew_point",
        name="Taupunkt",
        unit="°C",
        source_class="forecast",
        description="Stündliche Taupunktvorhersage.",
        coverage=_COVERAGE,
        temporal_resolution="stündlich",
    ),
    CapabilityInfo(
        id="relative_humidity",
        name="Relative Luftfeuchte",
        unit="%",
        source_class="forecast",
        description="Stündliche Vorhersage der relativen Luftfeuchte.",
        coverage=_COVERAGE,
        temporal_resolution="stündlich",
    ),
    CapabilityInfo(
        id="precipitation_probability",
        name="Niederschlagswahrscheinlichkeit",
        unit="%",
        source_class="forecast",
        description="Stündliche Niederschlagswahrscheinlichkeit.",
        coverage=_COVERAGE,
        temporal_resolution="stündlich",
    ),
    CapabilityInfo(
        id="wind_speed",
        name="Windgeschwindigkeit",
        unit="m/s",
        source_class="forecast",
        description="Stündliche Windgeschwindigkeitsvorhersage.",
        coverage=_COVERAGE,
        temporal_resolution="stündlich",
    ),
    CapabilityInfo(
        id="wind_direction",
        name="Windrichtung",
        unit="°",
        source_class="forecast",
        description="Stündliche Windrichtung; kardinale NWS-Angabe wird in Grad umgerechnet.",
        coverage=_COVERAGE,
        temporal_resolution="stündlich",
    ),
    CapabilityInfo(
        id="weather_summary",
        name="Wetterbeschreibung",
        unit=None,
        source_class="forecast",
        description="Kurze textuelle Wetterbeschreibung des NWS für die aktuelle Prognosestunde.",
        coverage=_COVERAGE,
        temporal_resolution="stündlich",
    ),
    CapabilityInfo(
        id="official_weather_alerts",
        name="Amtliche Wetterwarnungen · NWS",
        unit=None,
        source_class="warning",
        render_mode="hazard_feed",
        description=(
            "Aktive amtliche NWS Watches, Warnings und Advisories als normalisierter "
            "WeatherRouter-Gefahrenfeed."
        ),
        coverage=_COVERAGE,
        temporal_resolution="ereignisgesteuert / nahezu Echtzeit",
        strengths=(
            "amtliche CAP-basierte Warnungen",
            "GeoJSON-Geometrien soweit vom NWS veröffentlicht",
            "Tornado-, Gewitter-, Sturm-, Hagel- und Hochwasserwarnungen",
        ),
        limitations=("nur im NWS-Abdeckungsgebiet",),
        documentation_url="https://www.weather.gov/documentation/services-web-alerts",
    ),
)

_CAPABILITY_MAP = {item.id: item for item in _CAPABILITIES}
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_CARDINAL_DEGREES = {
    "N": 0.0,
    "NNE": 22.5,
    "NE": 45.0,
    "ENE": 67.5,
    "E": 90.0,
    "ESE": 112.5,
    "SE": 135.0,
    "SSE": 157.5,
    "S": 180.0,
    "SSW": 202.5,
    "SW": 225.0,
    "WSW": 247.5,
    "W": 270.0,
    "WNW": 292.5,
    "NW": 315.0,
    "NNW": 337.5,
}


def _quantity(raw: Any) -> tuple[float | None, str | None]:
    if not isinstance(raw, dict):
        return None, None
    value = raw.get("value")
    if not isinstance(value, (int, float)):
        return None, raw.get("unitCode") if isinstance(raw.get("unitCode"), str) else None
    unit = raw.get("unitCode")
    return float(value), unit if isinstance(unit, str) else None


def _temperature_c(period: dict[str, Any]) -> float | None:
    raw = period.get("temperature")
    value, unit = _quantity(raw)
    if value is not None:
        if unit in {"wmoUnit:degF", "unit:degF"}:
            return round((value - 32.0) * 5.0 / 9.0, 2)
        return round(value, 2)

    if isinstance(raw, (int, float)):
        if period.get("temperatureUnit") == "F":
            return round((float(raw) - 32.0) * 5.0 / 9.0, 2)
        return round(float(raw), 2)
    return None


def _celsius_quantity(raw: Any) -> float | None:
    value, unit = _quantity(raw)
    if value is None:
        return None
    if unit in {"wmoUnit:degF", "unit:degF"}:
        value = (value - 32.0) * 5.0 / 9.0
    return round(value, 2)


def _percent_quantity(raw: Any) -> float | None:
    value, _unit = _quantity(raw)
    return round(value, 1) if value is not None else None


def _wind_speed_ms(raw: Any) -> float | None:
    value, unit = _quantity(raw)
    if value is not None:
        if unit in {"wmoUnit:km_h-1", "unit:km_h-1"}:
            value /= 3.6
        elif unit in {"wmoUnit:mi_h-1", "unit:mi_h-1"}:
            value *= 0.44704
        return round(value, 2)

    if not isinstance(raw, str):
        return None
    values = [float(item) for item in _NUMBER_RE.findall(raw)]
    if not values:
        return None
    value = values[0]
    lower = raw.lower()
    if "mph" in lower:
        value *= 0.44704
    elif "km/h" in lower or "kmh" in lower:
        value /= 3.6
    return round(value, 2)


def _empty_result(requested: list[str], reason: str) -> dict[str, Any]:
    return {
        "provider": "noaa_nws",
        "provider_name": "NOAA / National Weather Service",
        "source_class": "forecast",
        "available": False,
        "coverage_status": "outside_coverage",
        "reason": reason,
        "values": {
            capability_id: {
                "value": None,
                "unit": _CAPABILITY_MAP[capability_id].unit,
            }
            for capability_id in requested
        },
        "attribution": "NOAA / National Weather Service",
    }


class NoaaNwsProvider:
    """NOAA/NWS API adapter for official U.S. point forecasts."""

    id = "noaa_nws"
    name = "NOAA / National Weather Service"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Offizielle Wetter-API des US National Weather Service für Vorhersagen, "
                "Warnungen und Beobachtungen in den USA und zugehörigen Gebieten."
            ),
            coverage=_COVERAGE,
            strengths=(
                "offizielle NOAA/NWS-Quelle",
                "kostenfrei und ohne API-Schlüssel",
                "stündliche lokale Vorhersagen",
                "separate Warnungs- und Beobachtungsdienste verfügbar",
            ),
            limitations=(
                "kein globaler Wetteranbieter",
                "User-Agent ist verpflichtend",
                "angemessene, nicht öffentlich bezifferte Ratenbegrenzung",
            ),
            documentation_url="https://www.weather.gov/documentation/services-web-api",
            attribution="NOAA / National Weather Service",
            services=(
                {
                    "name": "NWS API · Hourly Forecast",
                    "status": "integriert",
                    "note": "stündliche Punktvorhersage im NWS-Abdeckungsgebiet",
                },
                {
                    "name": "NWS Alerts",
                    "status": "integriert",
                    "note": "aktive CAP/GeoJSON Watches, Warnings und Advisories als hazard_feed",
                },
                {
                    "name": "NWS Observations",
                    "status": "katalogisiert",
                    "note": "Stationsbeobachtungen; regionale Verfügbarkeit",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="point_weather_forecast",
                scheme="https",
                host="api.weather.gov",
                port=443,
                target_type="api",
                required=True,
                capabilities=tuple(item.id for item in _CAPABILITIES),
                note=(
                    "WeatherRouter nutzt /points zur Ermittlung des zuständigen Forecast-Grids "
                    "und danach den offiziellen forecastHourly-Endpunkt."
                ),
            ),
        )

    async def async_fetch_point(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        capability_ids: list[str],
    ) -> dict[str, Any]:
        requested = list(
            dict.fromkeys(item for item in capability_ids if item in _CAPABILITY_MAP)
        )
        if not requested:
            return {
                "provider": self.id,
                "provider_name": self.name,
                "source_class": "forecast",
                "values": {},
            }

        session = async_get_clientsession(hass)
        point_url = f"{_API}/points/{float(latitude):.4f},{float(longitude):.4f}"
        async with session.get(point_url, headers=_HEADERS, timeout=20) as response:
            if response.status == 404:
                return _empty_result(
                    requested,
                    "Koordinate liegt außerhalb des NOAA/NWS-Abdeckungsgebiets.",
                )
            response.raise_for_status()
            point_payload = await response.json()

        point_properties = point_payload.get("properties")
        if not isinstance(point_properties, dict):
            raise ValueError("NOAA/NWS points response has no properties object")

        forecast_url = point_properties.get("forecastHourly")
        if not isinstance(forecast_url, str) or not forecast_url.startswith("https://api.weather.gov/"):
            raise ValueError("NOAA/NWS points response has no safe hourly forecast URL")

        async with session.get(
            forecast_url,
            headers=_FORECAST_HEADERS,
            timeout=20,
        ) as response:
            if response.status == 404:
                return _empty_result(
                    requested,
                    "Für diese Koordinate ist keine stündliche NWS-Vorhersage verfügbar.",
                )
            response.raise_for_status()
            forecast_payload = await response.json()

        properties = forecast_payload.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("NOAA/NWS hourly forecast response has no properties object")
        periods = properties.get("periods")
        if not isinstance(periods, list) or not periods:
            raise ValueError("NOAA/NWS hourly forecast response has no periods")

        period = periods[0]
        if not isinstance(period, dict):
            raise ValueError("NOAA/NWS first hourly forecast period is invalid")

        extracted = {
            "temperature": _temperature_c(period),
            "dew_point": _celsius_quantity(period.get("dewpoint")),
            "relative_humidity": _percent_quantity(period.get("relativeHumidity")),
            "precipitation_probability": _percent_quantity(
                period.get("probabilityOfPrecipitation")
            ),
            "wind_speed": _wind_speed_ms(period.get("windSpeed")),
            "wind_direction": _CARDINAL_DEGREES.get(
                str(period.get("windDirection") or "").upper()
            ),
            "weather_summary": period.get("shortForecast")
            if isinstance(period.get("shortForecast"), str)
            else None,
        }

        values = {
            capability_id: {
                "value": extracted.get(capability_id),
                "unit": _CAPABILITY_MAP[capability_id].unit,
            }
            for capability_id in requested
        }

        return {
            "provider": self.id,
            "provider_name": self.name,
            "source_class": "forecast",
            "available": True,
            "coverage_status": "inside_coverage",
            "latitude": round(float(latitude), 4),
            "longitude": round(float(longitude), 4),
            "data_time": period.get("startTime"),
            "updated_at": properties.get("updated"),
            "office": point_properties.get("gridId"),
            "values": values,
            "attribution": "NOAA / National Weather Service",
        }

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
        """Return normalized active NWS watches/warnings/advisories."""
        if capability_id != "official_weather_alerts":
            raise ValueError(f"Unsupported NOAA/NWS hazard capability: {capability_id}")

        params: dict[str, str] = {}
        if latitude is not None and longitude is not None:
            params["point"] = f"{float(latitude):.4f},{float(longitude):.4f}"

        session = async_get_clientsession(hass)
        async with session.get(
            f"{_API}/alerts/active",
            params=params,
            headers=_HEADERS,
            timeout=25,
        ) as response:
            if response.status == 404 and params:
                return {
                    "provider": self.id,
                    "provider_name": self.name,
                    "capability": capability_id,
                    "source_class": "warning",
                    "render_mode": "hazard_feed",
                    "coverage_status": "outside_coverage",
                    "events": [],
                    "attribution": "NOAA / National Weather Service",
                }
            response.raise_for_status()
            payload = await response.json()

        features = payload.get("features")
        if not isinstance(features, list):
            raise ValueError("NOAA/NWS alerts response has no features array")

        events: list[dict[str, Any]] = []
        missing_geometry_count = 0
        valid_feature_count = 0
        geometry_feature_count = 0
        for feature in features:
            if not isinstance(feature, dict):
                continue
            valid_feature_count += 1
            geometry = feature.get("geometry")
            if isinstance(geometry, dict):
                geometry_feature_count += 1
            elif bbox is not None:
                missing_geometry_count += 1
            if not geometry_intersects_bbox_strict(
                geometry if isinstance(geometry, dict) else None,
                bbox,
            ):
                continue
            properties = feature.get("properties")
            if not isinstance(properties, dict):
                continue

            event_name = properties.get("event")
            headline = properties.get("headline")
            description = properties.get("description")
            instruction = properties.get("instruction")
            hazard_type = normalize_hazard_type(
                event_name,
                headline,
                description,
                instruction,
            )
            event_id = properties.get("id") or feature.get("id")
            event_payload: dict[str, Any] = {
                    "id": str(event_id or ""),
                    "hazard_type": hazard_type,
                    "event": event_name,
                    "headline": headline,
                    "severity": normalize_severity(properties.get("severity")),
                    "urgency": properties.get("urgency"),
                    "certainty": properties.get("certainty"),
                    "status": properties.get("status"),
                    "message_type": properties.get("messageType"),
                    "sent": properties.get("sent"),
                    "effective": properties.get("effective"),
                    "onset": properties.get("onset"),
                    "expires": properties.get("expires"),
                    "ends": properties.get("ends"),
                    "area_desc": properties.get("areaDesc"),
                    "geometry": geometry if isinstance(geometry, dict) else None,
                    "description": description,
                    "instruction": instruction,
                    "sender_name": properties.get("senderName"),
                    "response": properties.get("response"),
                    "affected_zones": properties.get("affectedZones")
                    if isinstance(properties.get("affectedZones"), list)
                    else [],
                    "parameters": properties.get("parameters")
                    if isinstance(properties.get("parameters"), dict)
                    else {},
                    "web_url": str(event_id) if isinstance(event_id, str) else None,
                }
            semantic_class = tornado_semantic_class(hazard_type)
            if semantic_class is not None:
                event_payload.update(
                    {
                        "tornado_semantic_class": semantic_class,
                        "alert_stage": normalize_alert_stage(event_name, headline),
                        "hazard_match_scope": tornado_hazard_match_scope(
                            hazard_type,
                            event=event_name,
                            headline=headline,
                            description=description,
                            instruction=instruction,
                        ),
                    }
                )

            hail_class = hail_semantic_class(
                event_name,
                headline,
                description,
                instruction,
            )
            if hail_class is not None:
                event_payload.update(
                    {
                        "hail_semantic_class": hail_class,
                        "hail_match_scope": hail_hazard_match_scope(
                            event=event_name,
                            headline=headline,
                            description=description,
                            instruction=instruction,
                        ),
                    }
                )
                event_payload.setdefault(
                    "alert_stage",
                    normalize_alert_stage(event_name, headline),
                )

            wind_hazard_class = wind_hazard_semantic_class(
                event_name,
                headline,
                description,
                instruction,
            )
            if wind_hazard_class is not None:
                event_payload.update(
                    {
                        "wind_hazard_semantic_class": wind_hazard_class,
                        "wind_hazard_match_scope": wind_hazard_match_scope(
                            event=event_name,
                            headline=headline,
                            description=description,
                            instruction=instruction,
                        ),
                    }
                )
                event_payload.setdefault(
                    "alert_stage",
                    normalize_alert_stage(event_name, headline),
                )

            supercell_class = supercell_semantic_class(
                event_name,
                headline,
                description,
                instruction,
            )
            if supercell_class is not None:
                event_payload.update(
                    {
                        "supercell_semantic_class": supercell_class,
                        "supercell_match_scope": supercell_hazard_match_scope(
                            event=event_name,
                            headline=headline,
                            description=description,
                            instruction=instruction,
                        ),
                    }
                )
                event_payload.setdefault(
                    "alert_stage",
                    normalize_alert_stage(event_name, headline),
                )

            flood_matches = flood_semantics(
                event=event_name,
                headline=headline,
                description=description,
                instruction=instruction,
            )
            if flood_matches:
                event_payload["flood_semantics"] = flood_matches
                event_payload.setdefault(
                    "alert_stage",
                    normalize_alert_stage(event_name, headline),
                )

            tropical_system = tropical_system_from_explicit_text(
                event_name,
                headline,
            )
            if tropical_system is not None:
                event_payload["tropical_system"] = tropical_system
            events.append(event_payload)
            if len(events) >= max(1, min(int(limit), 1000)):
                break

        mode = "point" if params else "bbox" if bbox is not None else "global"
        matched_count = len(events)
        return {
            "provider": self.id,
            "provider_name": self.name,
            "capability": capability_id,
            "source_class": "warning",
            "render_mode": "hazard_feed",
            "coverage_status": (
                "inside_coverage"
                if mode == "point"
                else "context_match"
                if mode == "bbox" and matched_count > 0
                else "unknown"
                if mode == "bbox"
                else "regional"
            ),
            "events": events,
            "event_count": matched_count,
            "attribution": "NOAA / National Weather Service",
            "geometry_status": (
                "geojson"
                if geometry_feature_count > 0
                else "no_active_geometry"
            ),
            "spatial_filter": {
                "mode": mode,
                "input_event_count": valid_feature_count,
                "matched_event_count": matched_count,
                "geometry_event_count": geometry_feature_count,
                "excluded_missing_geometry": missing_geometry_count,
                "event_relevance_evidence": (
                    "provider_point_filter"
                    if mode == "point"
                    else "runtime_event_geometry"
                    if mode == "bbox"
                    else "official_alert_feed"
                ),
                "authority_coverage_status": (
                    "inside_coverage"
                    if mode == "point"
                    else "event_match_proven"
                    if mode == "bbox" and matched_count > 0
                    else "unknown"
                    if mode == "bbox"
                    else "regional_declared"
                ),
                "zero_matches_mean": (
                    "no_active_matching_warning_not_outside_coverage"
                    if mode == "bbox" and matched_count == 0
                    else None
                ),
            },
        }
