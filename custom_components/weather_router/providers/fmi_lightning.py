"""Official FMI open-data lightning observations for WeatherRouter."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import math
from typing import Any
import xml.etree.ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_PROVIDER_REVISION = "wr-0.10.76-fmi-lightning-1"
_WFS = "https://opendata.fmi.fi/wfs"
_STORED_QUERY = "fmi::observations::lightning::multipointcoverage"
_DEFAULT_BBOX = (5.0, 50.0, 35.0, 72.0)
_LOOKBACK_MINUTES = 20

_CAPABILITIES = (
    CapabilityInfo(
        id="lightning_strikes_observed",
        name="FMI · Live-Blitzbeobachtungen",
        unit=None,
        source_class="observation",
        render_mode="event_feed",
        description=(
            "Offizielle Blitzbeobachtungen des Finnish Meteorological Institute "
            "über den FMI Open Data WFS."
        ),
        coverage="Finnland und nördliches Europa gemäß FMI-Blitzbeobachtungsnetz",
        temporal_resolution="Ereignisse mit Sekundenauflösung; typischerweise <1 Minute Verzögerung",
        strengths=(
            "offizielle FMI-Open-Data-Quelle",
            "keine Zugangsdaten erforderlich",
            "Position und Zeit je Ereignis",
            "Peak Current, Multiplicity, Cloud Indicator und Ortungsellipse",
        ),
        limitations=(
            "regional auf die FMI-Blitzbeobachtungsabdeckung begrenzt",
            "kein globales Blitznetz",
            "Beobachtung, keine amtliche Warnung",
        ),
        documentation_url="https://en.ilmatieteenlaitos.fi/open-data-manual",
    ),
    CapabilityInfo(
        id="lightning_nearest_distance",
        name="FMI · nächster Blitz · Entfernung",
        unit="km",
        source_class="observation",
        render_mode="value",
        description="Entfernung zum nächsten FMI-Blitz im aktuellen Abfragefenster.",
        coverage="FMI-Blitzbeobachtungsgebiet",
        temporal_resolution="Live · 20-Minuten-Abfragefenster",
    ),
    CapabilityInfo(
        id="lightning_nearest_azimuth",
        name="FMI · nächster Blitz · Azimut",
        unit="°",
        source_class="observation",
        render_mode="value",
        description="Azimut zum nächsten FMI-Blitz im aktuellen Abfragefenster.",
        coverage="FMI-Blitzbeobachtungsgebiet",
        temporal_resolution="Live · 20-Minuten-Abfragefenster",
    ),
)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _distance_azimuth(
    latitude: float,
    longitude: float,
    strike_latitude: float,
    strike_longitude: float,
) -> tuple[float, float]:
    phi1 = math.radians(latitude)
    phi2 = math.radians(strike_latitude)
    dphi = phi2 - phi1
    dlambda = math.radians(strike_longitude - longitude)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    a = min(1.0, max(0.0, a))
    distance = 6371.0088 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return round(distance, 1), round(bearing, 1)


def _query_bbox(
    *,
    latitude: float | None,
    longitude: float | None,
    bbox: tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float]:
    if bbox is not None:
        return bbox
    if latitude is not None and longitude is not None:
        # Roughly a few hundred kilometres around the requested point; enough for
        # "nearest lightning" while keeping FMI request volume bounded.
        lon_span = max(2.5, 4.0 / max(0.35, math.cos(math.radians(latitude))))
        return (
            max(-180.0, longitude - lon_span),
            max(-90.0, latitude - 3.0),
            min(180.0, longitude + lon_span),
            min(90.0, latitude + 3.0),
        )
    return _DEFAULT_BBOX


def _field_names(root: ET.Element) -> list[str]:
    names: list[str] = []
    for element in root.iter():
        if element.tag == "{http://www.opengis.net/swe/2.0}field":
            name = element.attrib.get("name")
            if name:
                names.append(name)
    return names


def _first_text(root: ET.Element, tag: str) -> str | None:
    for element in root.iter():
        if element.tag == tag:
            return element.text
    return None


def _parse_events(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    positions_text = _first_text(
        root,
        "{http://www.opengis.net/gmlcov/1.0}positions",
    )
    tuple_text = _first_text(
        root,
        "{http://www.opengis.net/gml/3.2}doubleOrNilReasonTupleList",
    )
    if not positions_text or not tuple_text:
        return []

    position_values = [float(item) for item in positions_text.split()]
    if len(position_values) % 3:
        raise ValueError("FMI lightning positions are not lat/lon/time triples")

    fields = _field_names(root)
    if not fields:
        raise ValueError("FMI lightning response has no SWE fields")

    data_values: list[float | None] = []
    for token in tuple_text.split():
        lowered = token.lower()
        if lowered in {"nil", "nan", "null", "none"}:
            data_values.append(None)
        else:
            try:
                data_values.append(float(token))
            except ValueError:
                data_values.append(None)

    rows = len(position_values) // 3
    if len(data_values) < rows * len(fields):
        raise ValueError("FMI lightning tuple list is shorter than declared fields")

    events: list[dict[str, Any]] = []
    for index in range(rows):
        latitude = position_values[index * 3]
        longitude = position_values[index * 3 + 1]
        epoch = position_values[index * 3 + 2]
        observed = datetime.fromtimestamp(epoch, tz=timezone.utc)
        start = index * len(fields)
        values = {
            field: data_values[start + offset]
            for offset, field in enumerate(fields)
        }
        material = f"{int(epoch)}:{latitude:.5f}:{longitude:.5f}".encode()
        event_id = hashlib.blake2s(material, digest_size=12).hexdigest()
        cloud_indicator = values.get("cloud_indicator")
        events.append(
            {
                "id": event_id,
                "event_type": "lightning_strike",
                "observed_at": _iso(observed),
                "latitude": latitude,
                "longitude": longitude,
                "peak_current_ka": values.get("peak_current"),
                "multiplicity": values.get("multiplicity"),
                "cloud_indicator": cloud_indicator,
                "lightning_type": (
                    "cloud"
                    if cloud_indicator == 1
                    else "ground_or_unspecified"
                    if cloud_indicator is not None
                    else None
                ),
                "ellipse_major_km": values.get("ellipse_major"),
                "source": "fmi_open_data",
            }
        )
    return events


class FmiLightningProvider:
    """FMI Open Data WFS lightning observations."""

    id = "fmi_lightning"
    name = "FMI · Lightning Open Data"
    router_display_group = "thunderstorm"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Offizielle offene Blitzbeobachtungen des Finnish Meteorological "
                "Institute über den WFS-Download-Service."
            ),
            coverage="Finnland und nördliches Europa",
            strengths=(
                "offizielle Wetterdienstquelle",
                "ohne API-Schlüssel",
                "Sekundenauflösung",
                "Peak Current / Multiplicity / Cloud Indicator / Ortungsellipse",
                "CC BY 4.0 Open Data",
            ),
            limitations=(
                "regional begrenzt",
                "FMI Request-Limits beachten",
                "Beobachtung statt amtlicher Warnung",
            ),
            documentation_url="https://en.ilmatieteenlaitos.fi/open-data-manual",
            attribution="Finnish Meteorological Institute Open Data · CC BY 4.0",
            services=(
                {
                    "name": "FMI WFS · Lightning Strikes",
                    "status": "integriert",
                    "note": _STORED_QUERY,
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="official_lightning_observations",
                scheme="https",
                host="opendata.fmi.fi",
                port=443,
                target_type="wfs",
                required=True,
                capabilities=tuple(item.id for item in _CAPABILITIES),
                note=(
                    "FMI Open Data WFS lightning observations. "
                    "Download service limits apply."
                ),
            ),
        )

    async def _async_events(
        self,
        hass: HomeAssistant,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        west, south, east, north = _query_bbox(
            latitude=latitude,
            longitude=longitude,
            bbox=bbox,
        )
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=_LOOKBACK_MINUTES)
        session = async_get_clientsession(hass)
        async with session.get(
            _WFS,
            params={
                "service": "WFS",
                "version": "2.0.0",
                "request": "getFeature",
                "storedquery_id": _STORED_QUERY,
                "starttime": _iso(start),
                "endtime": _iso(now),
                "bbox": f"{west:.4f},{south:.4f},{east:.4f},{north:.4f},EPSG:4326",
            },
            headers={
                "Accept": "application/xml,text/xml",
                "User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)",
            },
            timeout=25,
        ) as response:
            response.raise_for_status()
            payload = await response.text()

        events = _parse_events(payload)
        if latitude is not None and longitude is not None:
            for event in events:
                distance, azimuth = _distance_azimuth(
                    latitude,
                    longitude,
                    event["latitude"],
                    event["longitude"],
                )
                event["distance_km"] = distance
                event["azimuth_deg"] = azimuth

        events.sort(key=lambda item: item["observed_at"], reverse=True)
        return events[: max(1, min(int(limit), 1000))]

    async def async_get_event_feed(
        self,
        hass: HomeAssistant,
        capability_id: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        if capability_id != "lightning_strikes_observed":
            raise ValueError(f"Unsupported FMI lightning capability: {capability_id}")

        events = await self._async_events(
            hass,
            latitude=latitude,
            longitude=longitude,
            bbox=bbox,
            limit=limit,
        )
        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "source_class": "observation",
            "render_mode": "event_feed",
            "available": True,
            "source_semantics": "official_lightning_observation",
            "data_time": events[0]["observed_at"] if events else None,
            "window_seconds": _LOOKBACK_MINUTES * 60,
            "events": events,
            "event_count": len(events),
            "attribution": "Finnish Meteorological Institute Open Data · CC BY 4.0",
            "provider_metadata": {
                "stored_query": _STORED_QUERY,
                "measurement": "lightning strike observation",
                "official_source": True,
                "license": "CC BY 4.0",
            },
        }

    async def async_fetch_point(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        capability_ids: list[str],
    ) -> dict[str, Any]:
        requested = [
            item
            for item in dict.fromkeys(capability_ids)
            if item in {"lightning_nearest_distance", "lightning_nearest_azimuth"}
        ]
        events = await self._async_events(
            hass,
            latitude=latitude,
            longitude=longitude,
            limit=1000,
        )
        nearest = min(events, key=lambda item: item.get("distance_km", float("inf"))) if events else None
        values: dict[str, dict[str, Any]] = {}
        for capability_id in requested:
            if capability_id == "lightning_nearest_distance":
                values[capability_id] = {
                    "value": nearest.get("distance_km") if nearest else None,
                    "unit": "km",
                }
            elif capability_id == "lightning_nearest_azimuth":
                values[capability_id] = {
                    "value": nearest.get("azimuth_deg") if nearest else None,
                    "unit": "°",
                }

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "source_class": "observation",
            "available": True,
            "data_time": nearest.get("observed_at") if nearest else None,
            "values": values,
            "attribution": "Finnish Meteorological Institute Open Data · CC BY 4.0",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            events = await self._async_events(hass, limit=25)
        except Exception as err:  # noqa: BLE001
            return {
                "ok": False,
                "stage": "fmi_lightning_wfs",
                "provider_revision": _PROVIDER_REVISION,
                "error": {"type": type(err).__name__, "message": str(err)},
            }
        return {
            "ok": True,
            "stage": "fmi_lightning_wfs",
            "provider_revision": _PROVIDER_REVISION,
            "stored_query": _STORED_QUERY,
            "event_count": len(events),
            "latest_observed_at": events[0]["observed_at"] if events else None,
            "lookback_minutes": _LOOKBACK_MINUTES,
            "official_source": True,
            "license": "CC BY 4.0",
        }
