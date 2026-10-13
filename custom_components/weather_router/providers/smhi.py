"""SMHI SNOW1gv1 point forecast provider."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_BASE = "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/geotype/point"
_PROVIDER_REVISION = "wr-0.10.119-snow1g-thunder-interval-2"

_FIELDS = {
    "temperature": ("air_temperature", "°C"),
    "relative_humidity": ("relative_humidity", "%"),
    "wind_direction": ("wind_from_direction", "°"),
    "wind_speed": ("wind_speed", "m/s"),
    "wind_gusts": ("wind_speed_of_gust", "m/s"),
    "air_pressure": ("air_pressure_at_mean_sea_level", "hPa"),
    "visibility": ("visibility_in_air", "km"),
    "thunder_probability": ("thunderstorm_probability", "%"),
    "cloud_cover": ("cloud_area_fraction", "%"),
    "cloud_cover_low": ("low_type_cloud_area_fraction", "%"),
    "cloud_cover_mid": ("medium_type_cloud_area_fraction", "%"),
    "cloud_cover_high": ("high_type_cloud_area_fraction", "%"),
    "precipitation": ("precipitation_amount_mean_deterministic", "mm"),
    "precipitation_probability": ("probability_of_precipitation", "%"),
    "weather_code": ("symbol_code", None),
}

_NAMES = {
    "temperature": "Temperatur",
    "relative_humidity": "Relative Luftfeuchte",
    "wind_direction": "Windrichtung",
    "wind_speed": "Windgeschwindigkeit",
    "wind_gusts": "Windböen",
    "air_pressure": "Luftdruck Meereshöhe",
    "visibility": "Sichtweite",
    "thunder_probability": "Gewitterwahrscheinlichkeit",
    "cloud_cover": "Wolken gesamt",
    "cloud_cover_low": "Tiefe Wolken",
    "cloud_cover_mid": "Mittlere Wolken",
    "cloud_cover_high": "Hohe Wolken",
    "precipitation": "Niederschlag",
    "precipitation_probability": "Niederschlagswahrscheinlichkeit",
    "weather_code": "Wettersymbol-Code",
}

_CAPABILITIES = tuple(
    CapabilityInfo(
        id=cap,
        name=_NAMES[cap],
        unit=unit,
        source_class="model",
        render_mode="value",
        description=f"SMHI SNOW1gv1 · {field}.",
        coverage="Schweden / Nordics / Baltikum",
        temporal_resolution="modellabhängig",
        strengths=("offizielle SMHI-Quelle", "hochaufgelöster regionaler Forecast"),
        limitations=("außerhalb des SNOW1g-Gebiets nicht verfügbar",),
        documentation_url="https://opendata.smhi.se/apidocs/metfcst/index.html",
    )
    for cap, (field, unit) in _FIELDS.items()
)
_CAPABILITY_MAP = {item.id: item for item in _CAPABILITIES}


def _empty_result(requested: list[str], reason: str) -> dict[str, Any]:
    return {
        "provider": "smhi",
        "provider_name": "SMHI",
        "provider_revision": _PROVIDER_REVISION,
        "source_class": "model",
        "available": False,
        "coverage_status": "outside_coverage",
        "reason": reason,
        "values": {
            cap: {"value": None, "unit": _CAPABILITY_MAP[cap].unit}
            for cap in requested
        },
        "attribution": "SMHI Open Data",
    }


def _clean(value: Any) -> Any:
    if isinstance(value, (int, float)) and float(value) == 9999.0:
        return None
    return value


class SmhiProvider:
    """SMHI SNOW1gv1 point forecast adapter."""

    id = "smhi"
    name = "SMHI"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "SMHI stellt offene hochaufgelöste Vorhersagedaten bereit. "
                "WeatherRouter nutzt die aktuelle SNOW1gv1-Punkt-API."
            ),
            coverage="Schweden, Nordics und angrenzender Ostseeraum",
            strengths=(
                "offizieller schwedischer Wetterdienst",
                "JSON-Punktvorhersage",
                "breites Set an Modellparametern",
            ),
            limitations=(
                "regional begrenzt",
                "SNOW1gv1 ersetzt ältere PMP3-Schnittstellen",
            ),
            documentation_url="https://opendata.smhi.se/apidocs/metfcst/index.html",
            attribution="SMHI Open Data",
            services=(
                {
                    "name": "SNOW1gv1",
                    "status": "integriert",
                    "note": "Punktvorhersage · JSON",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="point_weather_forecast",
                scheme="https",
                host="opendata-download-metfcst.smhi.se",
                port=443,
                target_type="api",
                required=True,
                capabilities=tuple(_CAPABILITY_MAP),
                note="SMHI SNOW1gv1 point forecast.",
            ),
        )

    async def async_fetch_point(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        capability_ids: list[str],
    ) -> dict[str, Any]:
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

        url = f"{_BASE}/lon/{float(longitude):.4f}/lat/{float(latitude):.4f}/data.json"
        params = ",".join(_FIELDS[item][0] for item in requested)
        session = async_get_clientsession(hass)
        async with session.get(
            url,
            params={"timeseries": "1", "parameters": params},
            headers={"Accept": "application/json"},
            timeout=20,
        ) as response:
            if response.status in {400, 404}:
                return _empty_result(
                    requested,
                    "Koordinate liegt außerhalb des SMHI-SNOW1g-Abdeckungsgebiets.",
                )
            response.raise_for_status()
            payload = await response.json()

        series = payload.get("timeSeries")
        if not isinstance(series, list) or not series:
            return _empty_result(requested, "SMHI lieferte keine Vorhersagezeitreihe.")

        first = series[0]
        data = first.get("data") if isinstance(first, dict) else None
        if not isinstance(data, dict):
            raise ValueError("SMHI SNOW1g first time step contains no data object")

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "source_class": "model",
            "available": True,
            "coverage_status": "inside_coverage",
            "data_time": first.get("time"),
            "updated_at": payload.get("createdTime"),
            "values": {
                cap: {
                    "value": _clean(data.get(_FIELDS[cap][0])),
                    "unit": _CAPABILITY_MAP[cap].unit,
                    "field": _FIELDS[cap][0],
                    **(
                        {
                            "interval_start": first.get("intervalParametersStartTime"),
                            "interval_end": first.get("time"),
                        }
                        if cap == "thunder_probability"
                        else {}
                    ),
                }
                for cap in requested
            },
            "attribution": "SMHI Open Data",
        }
