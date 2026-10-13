"""MET Norway multi-service provider for WeatherRouter."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_LOCATIONFORECAST_URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
_NOWCAST_URL = "https://api.met.no/weatherapi/nowcast/2.0/complete"
_USER_AGENT = "WeatherRouter/0.10 (https://github.com/TheDaimos)"
_PROVIDER_REVISION = "wr-0.10.36-nowcast-1"

_INSTANT_FIELDS = {
    "temperature": "air_temperature",
    "cloud_cover": "cloud_area_fraction",
    "cloud_cover_low": "cloud_area_fraction_low",
    "cloud_cover_mid": "cloud_area_fraction_medium",
    "cloud_cover_high": "cloud_area_fraction_high",
    "wind_speed": "wind_speed",
    "wind_direction": "wind_from_direction",
    "wind_gusts": "wind_speed_of_gust",
    "relative_humidity": "relative_humidity",
    "air_pressure": "air_pressure_at_sea_level",
    "dew_point": "dew_point_temperature",
    "fog": "fog_area_fraction",
    "uv_index": "ultraviolet_index_clear_sky",
}

_PERIOD_FIELDS = {
    "precipitation": "precipitation_amount",
    "precipitation_probability": "probability_of_precipitation",
    "thunder_probability": "probability_of_thunder",
}

_NOWCAST_INSTANT_FIELDS = {
    "nowcast_temperature": "air_temperature",
    "nowcast_precipitation_rate": "precipitation_rate",
    "nowcast_relative_humidity": "relative_humidity",
    "nowcast_wind_speed": "wind_speed",
    "nowcast_wind_direction": "wind_from_direction",
    "nowcast_wind_gusts": "wind_speed_of_gust",
}
_NOWCAST_PERIOD_FIELDS = {
    "nowcast_precipitation": "precipitation_amount",
}

_CAPABILITIES = (
    CapabilityInfo(
        "temperature", "Temperatur", "°C", "model", "value",
        "Lufttemperatur in 2 m Höhe.", "Global", "stündlich im Kurzfristbereich",
        None, ("hochaufgelöste nordische Modelle",), (),
        "https://api.met.no/weatherapi/locationforecast/2.0/documentation",
    ),
    CapabilityInfo("cloud_cover", "Wolken gesamt", "%", "model", "value",
        "Gesamtbewölkung.", "Global", "stündlich im Kurzfristbereich"),
    CapabilityInfo("cloud_cover_low", "Tiefe Wolken", "%", "model", "value",
        "Bedeckungsgrad tiefer Wolken.", "Global", "stündlich im Kurzfristbereich"),
    CapabilityInfo("cloud_cover_mid", "Mittlere Wolken", "%", "model", "value",
        "Bedeckungsgrad mittelhoher Wolken.", "Global", "stündlich im Kurzfristbereich"),
    CapabilityInfo("cloud_cover_high", "Hohe Wolken", "%", "model", "value",
        "Bedeckungsgrad hoher Wolken.", "Global", "stündlich im Kurzfristbereich"),
    CapabilityInfo("precipitation", "Niederschlag", "mm", "model", "value",
        "Erwartete Niederschlagsmenge für den nächsten verfügbaren Prognosezeitraum.",
        "Global", "1 h im Kurzfristbereich, später gröber"),
    CapabilityInfo("precipitation_probability", "Niederschlagswahrscheinlichkeit", "%", "model", "value",
        "Wahrscheinlichkeit für Niederschlag im nächsten verfügbaren Zeitraum.",
        "regional unterschiedlich", "1/6/12 h je nach Prognosehorizont"),
    CapabilityInfo("thunder_probability", "Gewitterwahrscheinlichkeit", "%", "model", "value",
        "Modellierte Gewitterwahrscheinlichkeit im nächsten verfügbaren Zeitraum.",
        "regional unterschiedlich", "1 h, sofern verfügbar",
        None, (), ("nicht in allen Regionen/Prognosehorizonten vorhanden",)),
    CapabilityInfo("wind_speed", "Windgeschwindigkeit 10 m", "m/s", "model", "value",
        "Mittlere Windgeschwindigkeit in 10 m Höhe.", "Global", "stündlich im Kurzfristbereich"),
    CapabilityInfo("wind_direction", "Windrichtung 10 m", "°", "model", "value",
        "Richtung, aus der der Wind kommt.", "Global", "stündlich im Kurzfristbereich"),
    CapabilityInfo("wind_gusts", "Windböen 10 m", "m/s", "model", "value",
        "Maximale Böe in 10 m Höhe.", "regional unterschiedlich", "Kurzfristbereich",
        None, (), ("nicht für alle Regionen und langen Prognosehorizonte verfügbar",)),
    CapabilityInfo("relative_humidity", "Relative Luftfeuchte", "%", "model", "value",
        "Relative Luftfeuchte in 2 m Höhe.", "Global", "stündlich im Kurzfristbereich"),
    CapabilityInfo("air_pressure", "Luftdruck Meereshöhe", "hPa", "model", "value",
        "Auf Meereshöhe reduzierter Luftdruck.", "Global", "stündlich im Kurzfristbereich"),
    CapabilityInfo("dew_point", "Taupunkt", "°C", "model", "value",
        "Taupunkttemperatur in 2 m Höhe.", "Global", "stündlich im Kurzfristbereich"),
    CapabilityInfo("fog", "Nebelanteil", "%", "model", "value",
        "Modellierter Flächenanteil mit Nebel.", "regional unterschiedlich", "Kurzfristbereich",
        None, (), ("nicht im gesamten Langfristbereich verfügbar",)),
    CapabilityInfo("uv_index", "UV-Index klarer Himmel", "1", "model", "value",
        "UV-Index bei wolkenfreiem Himmel.", "regional unterschiedlich", "Kurzfristbereich",
        None, (), ("nicht überall und nicht im gesamten Prognosehorizont verfügbar",)),
)

_NOWCAST_CAPABILITIES = (
    CapabilityInfo(
        "nowcast_temperature", "Nowcast · Temperatur", "°C", "forecast", "value",
        "MET Norway Nowcast 2.0 Lufttemperatur.", "Nordics / MEPS-Gebiet",
        "5-Minuten-Aktualisierung, bis 2 h",
        None, ("sehr kurzfristige Vorhersage", "offizielle MET-Quelle"), (),
        "https://api.met.no/weatherapi/nowcast/2.0/documentation",
    ),
    CapabilityInfo(
        "nowcast_precipitation_rate", "Nowcast · Niederschlagsrate", "mm/h", "forecast", "value",
        "Radar-gestützte aktuelle Niederschlagsrate.", "Nordics / Radarabdeckung",
        "5 Minuten", None, ("Radar-Nowcast",),
        ("nur bei ausreichender Radarabdeckung verfügbar",),
        "https://api.met.no/weatherapi/nowcast/2.0/documentation",
    ),
    CapabilityInfo(
        "nowcast_precipitation", "Nowcast · Niederschlag", "mm", "forecast", "value",
        "Niederschlagsmenge des nächsten verfügbaren Nowcast-Zeitraums.",
        "Nordics / Radarabdeckung", "5-Minuten-Aktualisierung", None,
        ("2-Stunden-Nowcast",), ("nur bei ausreichender Radarabdeckung verfügbar",),
        "https://api.met.no/weatherapi/nowcast/2.0/documentation",
    ),
    CapabilityInfo(
        "nowcast_relative_humidity", "Nowcast · Relative Luftfeuchte", "%", "forecast", "value",
        "Relative Luftfeuchte im MET-Nowcast.", "Nordics / MEPS-Gebiet", "5 Minuten",
    ),
    CapabilityInfo(
        "nowcast_wind_speed", "Nowcast · Windgeschwindigkeit", "m/s", "forecast", "value",
        "Windgeschwindigkeit im MET-Nowcast.", "Nordics / MEPS-Gebiet", "5 Minuten",
    ),
    CapabilityInfo(
        "nowcast_wind_direction", "Nowcast · Windrichtung", "°", "forecast", "value",
        "Windrichtung im MET-Nowcast.", "Nordics / MEPS-Gebiet", "5 Minuten",
    ),
    CapabilityInfo(
        "nowcast_wind_gusts", "Nowcast · Windböen", "m/s", "forecast", "value",
        "Windböen im MET-Nowcast.", "Nordics / MEPS-Gebiet", "5 Minuten",
    ),
)

_CAPABILITIES = _CAPABILITIES + _NOWCAST_CAPABILITIES
_LOCATION_CAPABILITY_IDS = {
    item.id for item in _CAPABILITIES if not item.id.startswith("nowcast_")
}
_NOWCAST_CAPABILITY_IDS = {
    item.id for item in _CAPABILITIES if item.id.startswith("nowcast_")
}
_CAPABILITY_MAP = {item.id: item for item in _CAPABILITIES}


def _period_details(data: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Return the shortest available forecast-period details."""
    for key, label in (
        ("next_1_hours", "1h"),
        ("next_6_hours", "6h"),
        ("next_12_hours", "12h"),
    ):
        block = data.get(key)
        if not isinstance(block, dict):
            continue
        details = block.get("details")
        if isinstance(details, dict):
            return details, label
    return {}, None


class MetNorwayProvider:
    """MET Norway WeatherAPI adapter."""

    id = "met_norway"
    name = "MET Norway"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        """Return directly integrated Locationforecast capabilities."""
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        """Return service strengths, restrictions and related MET products."""
        return ProviderInfo(
            summary=(
                "Meteorologisk institutt (MET Norway) betreibt eine offene WeatherAPI "
                "mit globalen Punktvorhersagen sowie regionalen Nowcast-, Radar- und "
                "Satellitenprodukten."
            ),
            coverage="Locationforecast global; weitere Dienste überwiegend nordisch oder produktspezifisch",
            strengths=(
                "offizielle meteorologische Datenquelle",
                "globale Locationforecast-Punktvorhersage",
                "im nordischen Raum häufig aktualisierte hochauflösende Modelle",
                "zusätzliche Satelliten-, Radar- und Nowcast-Dienste",
            ),
            limitations=(
                "eindeutiger identifizierender User-Agent ist verpflichtend",
                "Nowcast/Radar sind regional begrenzt",
                "Geosatellite liefert komplette PNG/Video-Produkte statt kachelbarer Kartenlayer",
            ),
            documentation_url="https://api.met.no/",
            attribution="Meteorologisk institutt / MET Norway · CC BY 4.0",
            services=(
                {
                    "name": "Locationforecast 2.0",
                    "status": "integriert",
                    "note": "globale Punktvorhersage · bis etwa 9 Tage",
                },
                {
                    "name": "Geosatellite 1.4",
                    "status": "katalogisiert",
                    "note": "sichtbar/IR · ganze PNG/Video-Bilder; eigener Image-Overlay-Vertrag nötig",
                },
                {
                    "name": "Nowcast 2.0",
                    "status": "integriert",
                    "note": "Nordics · 2 Stunden · Aktualisierung alle 5 Minuten",
                },
                {
                    "name": "Radar 2.0",
                    "status": "katalogisiert",
                    "note": "Nordics · statische Bilder/Animationen",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        """Return documented MET WeatherAPI endpoints."""
        capability_ids = tuple(item.id for item in _CAPABILITIES)
        return (
            NetworkTargetInfo(
                purpose="point_weather_forecast",
                scheme="https",
                host="api.met.no",
                port=443,
                target_type="api",
                required=True,
                capabilities=capability_ids,
                note=(
                    "Locationforecast 2.0. WeatherRouter sendet serverseitig einen "
                    "eindeutigen User-Agent; Koordinaten werden für Cachefreundlichkeit "
                    "auf vier Nachkommastellen begrenzt."
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
        """Fetch requested Locationforecast and/or Nowcast point values."""
        requested = list(dict.fromkeys(
            item for item in capability_ids if item in _CAPABILITY_MAP
        ))
        if not requested:
            return {
                "provider": self.id,
                "provider_name": self.name,
                "provider_revision": _PROVIDER_REVISION,
                "source_class": "model",
                "values": {},
            }

        location_requested = [item for item in requested if item in _LOCATION_CAPABILITY_IDS]
        nowcast_requested = [item for item in requested if item in _NOWCAST_CAPABILITY_IDS]
        session = async_get_clientsession(hass)
        values: dict[str, Any] = {}
        data_times: list[str] = []
        updated_times: list[str] = []
        nowcast_coverage: str | None = None

        if location_requested:
            async with session.get(
                _LOCATIONFORECAST_URL,
                params={
                    "lat": f"{float(latitude):.4f}",
                    "lon": f"{float(longitude):.4f}",
                },
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
                timeout=20,
            ) as response:
                response.raise_for_status()
                payload = await response.json()

            properties = payload.get("properties")
            if not isinstance(properties, dict):
                raise ValueError("MET Norway Locationforecast response has no properties object")
            timeseries = properties.get("timeseries")
            if not isinstance(timeseries, list) or not timeseries:
                raise ValueError("MET Norway Locationforecast response has no time series")
            first = timeseries[0]
            if not isinstance(first, dict) or not isinstance(first.get("data"), dict):
                raise ValueError("MET Norway Locationforecast first time step is invalid")
            data = first["data"]
            instant = data.get("instant")
            instant_details = (
                instant.get("details")
                if isinstance(instant, dict) and isinstance(instant.get("details"), dict)
                else {}
            )
            period_details, period = _period_details(data)
            meta = properties.get("meta") if isinstance(properties.get("meta"), dict) else {}
            units = meta.get("units") if isinstance(meta.get("units"), dict) else {}

            for capability_id in location_requested:
                if capability_id in _INSTANT_FIELDS:
                    field = _INSTANT_FIELDS[capability_id]
                    values[capability_id] = {
                        "value": instant_details.get(field),
                        "unit": units.get(field) or _CAPABILITY_MAP[capability_id].unit,
                        "field": field,
                    }
                else:
                    field = _PERIOD_FIELDS[capability_id]
                    values[capability_id] = {
                        "value": period_details.get(field),
                        "unit": units.get(field) or _CAPABILITY_MAP[capability_id].unit,
                        "field": field,
                        "period": period,
                    }
            if isinstance(first.get("time"), str):
                data_times.append(first["time"])
            if isinstance(meta.get("updated_at"), str):
                updated_times.append(meta["updated_at"])

        if nowcast_requested:
            async with session.get(
                _NOWCAST_URL,
                params={
                    "lat": f"{float(latitude):.4f}",
                    "lon": f"{float(longitude):.4f}",
                },
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
                timeout=20,
            ) as response:
                if response.status in {404, 422}:
                    for capability_id in nowcast_requested:
                        values[capability_id] = {
                            "value": None,
                            "unit": _CAPABILITY_MAP[capability_id].unit,
                        }
                    nowcast_coverage = "outside_coverage"
                else:
                    response.raise_for_status()
                    payload = await response.json()
                    properties = payload.get("properties")
                    if not isinstance(properties, dict):
                        raise ValueError("MET Norway Nowcast response has no properties object")
                    timeseries = properties.get("timeseries")
                    if not isinstance(timeseries, list) or not timeseries:
                        raise ValueError("MET Norway Nowcast response has no time series")
                    first = timeseries[0]
                    if not isinstance(first, dict) or not isinstance(first.get("data"), dict):
                        raise ValueError("MET Norway Nowcast first time step is invalid")
                    data = first["data"]
                    instant = data.get("instant")
                    instant_details = (
                        instant.get("details")
                        if isinstance(instant, dict) and isinstance(instant.get("details"), dict)
                        else {}
                    )
                    period_details, period = _period_details(data)
                    meta = properties.get("meta") if isinstance(properties.get("meta"), dict) else {}
                    units = meta.get("units") if isinstance(meta.get("units"), dict) else {}
                    radar_coverage = meta.get("radar_coverage") or meta.get("radarCoverage")
                    if radar_coverage is not None:
                        nowcast_coverage = str(radar_coverage)

                    for capability_id in nowcast_requested:
                        if capability_id in _NOWCAST_INSTANT_FIELDS:
                            field = _NOWCAST_INSTANT_FIELDS[capability_id]
                            values[capability_id] = {
                                "value": instant_details.get(field),
                                "unit": units.get(field) or _CAPABILITY_MAP[capability_id].unit,
                                "field": field,
                            }
                        else:
                            field = _NOWCAST_PERIOD_FIELDS[capability_id]
                            values[capability_id] = {
                                "value": period_details.get(field),
                                "unit": units.get(field) or _CAPABILITY_MAP[capability_id].unit,
                                "field": field,
                                "period": period,
                            }
                    if isinstance(first.get("time"), str):
                        data_times.append(first["time"])
                    if isinstance(meta.get("updated_at"), str):
                        updated_times.append(meta["updated_at"])

        result: dict[str, Any] = {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "source_class": (
                "mixed" if location_requested and nowcast_requested
                else "forecast" if nowcast_requested
                else "model"
            ),
            "latitude": round(float(latitude), 4),
            "longitude": round(float(longitude), 4),
            "data_time": min(data_times) if data_times else None,
            "updated_at": max(updated_times) if updated_times else None,
            "values": values,
            "attribution": "Weather data: Meteorologisk institutt (MET Norway), CC BY 4.0",
        }
        if nowcast_requested:
            result["nowcast_coverage"] = nowcast_coverage
        return result
