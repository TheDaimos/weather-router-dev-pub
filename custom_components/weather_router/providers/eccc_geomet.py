"""Environment and Climate Change Canada / MSC GeoMet observation provider."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_ITEMS_URL = "https://api.weather.gc.ca/collections/swob-realtime/items"

_FIELDS = {
    "temperature": (("air_temp",), "°C"),
    "dew_point": (("dwpt_temp",), "°C"),
    "relative_humidity": (("rel_hum",), "%"),
    "air_pressure": (("mslp", "stn_pres"), "hPa"),
    "visibility": (("vis", "min_vis_pst10mts"), "m"),
    "precipitation_1h": (("pcpn_amt_pst1hr", "rnfl_amt_pst1hr"), "mm"),
    "cloud_cover": (("tot_cld_amt",), None),
    "wind_direction": (
        (
            "wnd_dir_10m_pst10mts_max_spd",
            "wnd_dir_10m_pst1hr_max_spd",
            "wnd_dir_pst1hr_max_spd",
        ),
        "°",
    ),
}

_NAMES = {
    "temperature": "Temperatur",
    "dew_point": "Taupunkt",
    "relative_humidity": "Relative Luftfeuchte",
    "air_pressure": "Luftdruck",
    "visibility": "Sichtweite",
    "precipitation_1h": "Niederschlag letzte Stunde",
    "cloud_cover": "Wolkenbedeckung",
    "wind_direction": "Windrichtung",
}

_CAPABILITIES = tuple(
    CapabilityInfo(
        id=cap,
        name=_NAMES[cap],
        unit=unit,
        source_class="observation",
        render_mode="value",
        description="Aktuelle Stationsbeobachtung aus MSC GeoMet / SWOB.",
        coverage="Kanada und angeschlossene SWOB-Stationsnetze",
        temporal_resolution="stationsabhängig, nahe Echtzeit",
        strengths=("offizielle ECCC/MSC-Quelle", "reale Stationsbeobachtung"),
        limitations=(
            "Parameterverfügbarkeit ist stationsabhängig",
            "nächstgelegene Station kann einzelne Felder nicht liefern",
        ),
        documentation_url="https://api.weather.gc.ca/",
    )
    for cap, (_fields, unit) in _FIELDS.items()
)
_CAPABILITY_MAP = {item.id: item for item in _CAPABILITIES}


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(a))


def _first(props: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = props.get(name)
        if value is not None:
            return value
    return None


def _empty_result(
    requested: list[str],
    reason: str,
    *,
    coverage_status: str = "unknown",
    unavailable_code: str = "temporarily_unavailable",
) -> dict[str, Any]:
    """Return an unavailable point result without inventing spatial coverage."""
    return {
        "provider": "eccc_geomet",
        "provider_name": "ECCC / MSC GeoMet",
        "source_class": "observation",
        "available": False,
        "coverage_status": coverage_status,
        "unavailable_code": unavailable_code,
        "reason": reason,
        "values": {
            cap: {"value": None, "unit": _CAPABILITY_MAP[cap].unit}
            for cap in requested
        },
        "attribution": "Environment and Climate Change Canada / MSC GeoMet",
    }


class EcccGeometProvider:
    """Nearest SWOB real-time observation adapter."""

    id = "eccc_geomet"
    name = "ECCC / MSC GeoMet"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Environment and Climate Change Canada stellt über MSC GeoMet "
                "offene OGC-Dienste und aktuelle SWOB-Stationsbeobachtungen bereit."
            ),
            coverage="Kanada und angeschlossene Stationsnetze",
            strengths=(
                "offizielle kanadische Wetterquelle",
                "OGC API Features",
                "reale Oberflächenbeobachtungen",
                "zusätzliche GeoMet-WMS-Modell- und Radarprodukte",
            ),
            limitations=(
                "Stationsparameter sind nicht überall vollständig",
                "WeatherRouter nutzt für Punktwerte die nächstgelegene aktuelle SWOB-Station",
            ),
            documentation_url="https://api.weather.gc.ca/",
            attribution="Environment and Climate Change Canada / MSC GeoMet",
            services=(
                {
                    "name": "SWOB Real-Time",
                    "status": "integriert",
                    "note": "aktuelle Stationsbeobachtungen",
                },
                {
                    "name": "MSC GeoMet WMS",
                    "status": "katalogisiert",
                    "note": "Radar-, Analyse- und Modellkarten für späteren Rasterausbau",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="surface_observation",
                scheme="https",
                host="api.weather.gc.ca",
                port=443,
                target_type="ogc_api",
                required=True,
                capabilities=tuple(_CAPABILITY_MAP),
                note="MSC GeoMet OGC API · swob-realtime.",
            ),
            NetworkTargetInfo(
                purpose="weather_map_catalog",
                scheme="https",
                host="geo.weather.gc.ca",
                port=443,
                target_type="wms",
                required=False,
                capabilities=(),
                note="MSC GeoMet WMS, noch nicht als WeatherRouter-Rasterfähigkeit aktiviert.",
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
                "source_class": "observation",
                "values": {},
            }

        lat = float(latitude)
        lon = float(longitude)
        span = 1.5
        bbox = f"{lon-span:.4f},{lat-span:.4f},{lon+span:.4f},{lat+span:.4f}"

        session = async_get_clientsession(hass)
        async with session.get(
            _ITEMS_URL,
            params={"f": "json", "bbox": bbox, "limit": "100"},
            headers={"Accept": "application/geo+json,application/json"},
            timeout=25,
        ) as response:
            response.raise_for_status()
            payload = await response.json()

        features = payload.get("features")
        if not isinstance(features, list) or not features:
            return _empty_result(
                requested,
                "Keine aktuelle ECCC/SWOB-Station in der Umgebung gefunden.",
            )

        candidates: list[tuple[float, dict[str, Any]]] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            geometry = feature.get("geometry")
            coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
            if not isinstance(coords, list) or len(coords) < 2:
                continue
            try:
                station_lon = float(coords[0])
                station_lat = float(coords[1])
            except (TypeError, ValueError):
                continue
            candidates.append((
                _distance_km(lat, lon, station_lat, station_lon),
                feature,
            ))

        if not candidates:
            return _empty_result(requested, "SWOB-Antwort enthält keine nutzbaren Stationskoordinaten.")

        distance, nearest = min(candidates, key=lambda item: item[0])
        if distance > 200:
            return _empty_result(
                requested,
                "Nächstgelegene aktuelle ECCC/SWOB-Station ist zu weit entfernt.",
                coverage_status="outside_coverage",
                unavailable_code="outside_coverage",
            )

        props = nearest.get("properties")
        if not isinstance(props, dict):
            raise ValueError("ECCC SWOB feature contains no properties object")

        values = {}
        for cap in requested:
            fields, unit = _FIELDS[cap]
            value = _first(props, fields)
            provider_unit = None
            for field in fields:
                provider_unit = props.get(f"{field}-uom")
                if provider_unit:
                    break
            values[cap] = {
                "value": value,
                "unit": provider_unit or unit,
                "field": next((field for field in fields if props.get(field) is not None), fields[0]),
            }

        return {
            "provider": self.id,
            "provider_name": self.name,
            "source_class": "observation",
            "available": True,
            "coverage_status": "inside_coverage",
            "data_time": props.get("date_tm-value") or props.get("obs_date_tm"),
            "station": props.get("stn_nam-value") or props.get("stn_id-value"),
            "station_distance_km": round(distance, 1),
            "values": values,
            "attribution": "Environment and Climate Change Canada / MSC GeoMet",
        }
