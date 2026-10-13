"""Finnish Meteorological Institute HARMONIE point forecast provider."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_TIMESERIES_URL = "https://opendata.fmi.fi/timeseries"
_PRODUCER = "harmonie_scandinavia_surface"
_PROVIDER_REVISION = "wr-0.10.36-timeseries-1"

_FIELDS = {
    "temperature": ("Temperature", "°C"),
    "dew_point": ("DewPoint", "°C"),
    "relative_humidity": ("Humidity", "%"),
    "wind_direction": ("WindDirection", "°"),
    "wind_speed": ("WindSpeedMS", "m/s"),
    "wind_gusts": ("WindGust", "m/s"),
    "air_pressure": ("Pressure", "hPa"),
    "precipitation": ("Precipitation1h", "mm"),
    "cloud_cover": ("TotalCloudCover", "%"),
    "visibility": ("Visibility", "m"),
}

_NAMES = {
    "temperature": "Temperatur",
    "dew_point": "Taupunkt",
    "relative_humidity": "Relative Luftfeuchte",
    "wind_direction": "Windrichtung",
    "wind_speed": "Windgeschwindigkeit",
    "wind_gusts": "Windböen",
    "air_pressure": "Luftdruck",
    "precipitation": "Niederschlag 1 h",
    "cloud_cover": "Wolken gesamt",
    "visibility": "Sichtweite",
}

_CAPABILITIES = tuple(
    CapabilityInfo(
        id=capability_id,
        name=_NAMES[capability_id],
        unit=unit,
        source_class="model",
        render_mode="value",
        description=f"FMI HARMONIE/MEPS Punktvorhersage · {field}.",
        coverage="Skandinavien / HARMONIE-MEPS-Regionalgebiet",
        temporal_resolution="modellabhängig, im Kurzfristbereich typischerweise stündlich",
        strengths=("offizielle FMI-Quelle", "hochaufgelöstes HARMONIE/MEPS-Regionalmodell"),
        limitations=("außerhalb des Modellgebiets nicht verfügbar",),
        documentation_url="https://en.ilmatieteenlaitos.fi/open-data-manual",
    )
    for capability_id, (field, unit) in _FIELDS.items()
)
_CAPABILITY_MAP = {item.id: item for item in _CAPABILITIES}


def _clean_numeric(value: Any) -> Any:
    """Normalize SmartMet JSON number values without masking text/error values."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() in {"nan", "null", "none"}:
            return None
        try:
            return float(stripped)
        except ValueError:
            return value
    return value


def _empty_result(requested: list[str], reason: str) -> dict[str, Any]:
    return {
        "provider": "fmi",
        "provider_name": "FMI · Finnish Meteorological Institute",
        "provider_revision": _PROVIDER_REVISION,
        "source_class": "model",
        "available": False,
        "coverage_status": "outside_coverage",
        "reason": reason,
        "values": {
            cap: {"value": None, "unit": _CAPABILITY_MAP[cap].unit}
            for cap in requested
        },
        "attribution": "Finnish Meteorological Institute Open Data",
    }


class FmiProvider:
    """FMI SmartMet/HARMONIE point forecast adapter."""

    id = "fmi"
    name = "FMI · Finnish Meteorological Institute"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Der Finnish Meteorological Institute stellt offene HARMONIE/MEPS-"
                "Vorhersagedaten über SmartMet bereit. WeatherRouter nutzt für freie "
                "Koordinaten den offiziellen JSON-Timeseries-Weg."
            ),
            coverage="Skandinavien und HARMONIE/MEPS-Regionalgebiet",
            strengths=(
                "offizieller nationaler Wetterdienst",
                "koordinatenbasierte JSON-Punktabfrage",
                "hochaufgelöste Regionalvorhersage",
            ),
            limitations=("regional begrenzt",),
            documentation_url="https://en.ilmatieteenlaitos.fi/open-data-manual",
            attribution="Finnish Meteorological Institute Open Data",
            services=(
                {
                    "name": "HARMONIE/MEPS surface point forecast",
                    "status": "integriert",
                    "note": "SmartMet Timeseries · JSON · freie Koordinaten",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="point_weather_forecast",
                scheme="https",
                host="opendata.fmi.fi",
                port=443,
                target_type="api",
                required=True,
                capabilities=tuple(_CAPABILITY_MAP),
                note="FMI Open Data SmartMet timeseries / HARMONIE Scandinavia surface.",
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

        field_names = [_FIELDS[item][0] for item in requested]
        session = async_get_clientsession(hass)
        async with session.get(
            _TIMESERIES_URL,
            params={
                "producer": _PRODUCER,
                "latlon": f"{float(latitude):.4f},{float(longitude):.4f}",
                "param": ",".join(("utctime", *field_names)),
                "format": "json",
                "timesteps": "1",
                "timestep": "data",
                "precision": "double",
                "tz": "UTC",
            },
            headers={"Accept": "application/json"},
            timeout=25,
        ) as response:
            response.raise_for_status()
            payload = await response.json()

        if not isinstance(payload, list):
            raise ValueError("FMI SmartMet timeseries response is not a JSON list")
        if not payload:
            return _empty_result(
                requested,
                "FMI lieferte für diese Koordinate keine HARMONIE/MEPS-Punktwerte.",
            )

        row = payload[0]
        if not isinstance(row, dict):
            raise ValueError("FMI SmartMet timeseries first row is not an object")

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "source_class": "model",
            "available": True,
            "coverage_status": "inside_coverage",
            "data_time": row.get("utctime"),
            "values": {
                cap: {
                    "value": _clean_numeric(row.get(_FIELDS[cap][0])),
                    "unit": _CAPABILITY_MAP[cap].unit,
                    "field": _FIELDS[cap][0],
                }
                for cap in requested
            },
            "attribution": "Finnish Meteorological Institute Open Data",
        }
