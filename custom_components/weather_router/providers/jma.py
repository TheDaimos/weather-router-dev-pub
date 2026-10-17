"""Japan Meteorological Agency regional forecast provider."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import tsunami_semantics

_BASE = "https://www.jma.go.jp"
_FORECAST_AREA_URL = f"{_BASE}/bosai/forecast/const/forecast_area.json"
_AMEDAS_URL = f"{_BASE}/bosai/amedas/const/amedastable.json"
_JMA_XML_FEED_FAST = "https://www.data.jma.go.jp/developer/xml/feed/eqvol.xml"
_JMA_XML_FEED_LONG = "https://www.data.jma.go.jp/developer/xml/feed/eqvol_l.xml"
_PROVIDER_REVISION = "wr-0.10.129-tsunami-semantics-1"

_CAPABILITIES = (
    CapabilityInfo(
        "temperature", "Temperatur", "°C", "forecast", "value",
        "JMA-Gebietsvorhersage über die nächstgelegene zugeordnete AMeDAS-Station.",
        "Japan", "mehrmals täglich",
    ),
    CapabilityInfo(
        "precipitation_probability", "Niederschlagswahrscheinlichkeit", "%", "forecast", "value",
        "JMA-Niederschlagswahrscheinlichkeit der passenden Primärregion.",
        "Japan", "mehrmals täglich",
    ),
    CapabilityInfo(
        "weather_summary", "Wetterbeschreibung", None, "forecast", "value",
        "JMA-Wetterbeschreibung für die passende Primärregion.",
        "Japan", "mehrmals täglich",
    ),
    CapabilityInfo(
        "weather_code", "Wettercode", None, "forecast", "value",
        "JMA-Wettercode der passenden Primärregion.",
        "Japan", "mehrmals täglich",
    ),
    CapabilityInfo(
        "wind_summary", "Windbeschreibung", None, "forecast", "value",
        "JMA-Windbeschreibung der passenden Primärregion.",
        "Japan", "mehrmals täglich",
    ),
    CapabilityInfo(
        id="official_tsunami_warnings_japan",
        name="Amtliche Tsunamiwarnungen · JMA",
        unit=None,
        source_class="warning",
        render_mode="hazard_feed",
        description=(
            "JMA-Tsunamiwarnungen, -hinweise und -vorhersagen aus dem öffentlichen "
            "JMA-Bosai-XML-PULL-Dienst."
        ),
        coverage="Japanische Tsunami-Vorhersagegebiete",
        temporal_resolution="ereignisgesteuert",
        strengths=(
            "amtliche JMA-Quelle",
            "Warngebiet und Warnstufe",
            "erwartete Ankunftszeit und erwartete Tsunamihöhe soweit veröffentlicht",
        ),
        limitations=(
            "Warngebietsgeometrien werden zunächst über amtliche Gebietscodes geführt; "
            "GIS-Polygone werden separat ergänzt",
        ),
        documentation_url="https://www.data.jma.go.jp/developer/",
    ),
    CapabilityInfo(
        id="tsunami_observations_japan",
        name="Tsunami-Beobachtungen · JMA",
        unit=None,
        source_class="observation",
        render_mode="hazard_feed",
        description=(
            "Amtliche JMA-Tsunamiinformationen mit beobachteten Ankunftszeiten und "
            "Wellenhöhen an Küsten-/Offshore-Messstellen."
        ),
        coverage="Japan und zugehörige JMA-Tsunami-Messstellen",
        temporal_resolution="ereignisgesteuert",
        strengths=("amtliche Beobachtungen", "beobachtete Wellen statt bloßer Modellannahme"),
        limitations=("nur bei entsprechenden Tsunamiereignissen vorhanden",),
        documentation_url="https://www.data.jma.go.jp/developer/",
    ),
)
_CAPABILITY_MAP = {item.id: item for item in _CAPABILITIES}
_POINT_CAPABILITY_MAP = {
    item.id: item for item in _CAPABILITIES if item.render_mode == "value"
}


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radius * asin(sqrt(a))


def _station_coord(raw: Any) -> float | None:
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    try:
        return float(raw[0]) + float(raw[1]) / 60.0
    except (TypeError, ValueError):
        return None


def _empty_result(requested: list[str], reason: str) -> dict[str, Any]:
    return {
        "provider": "jma",
        "provider_name": "JMA · Japan Meteorological Agency",
        "source_class": "forecast",
        "available": False,
        "coverage_status": "outside_coverage",
        "reason": reason,
        "values": {
            cap: {"value": None, "unit": _POINT_CAPABILITY_MAP[cap].unit}
            for cap in requested
        },
        "attribution": "Japan Meteorological Agency",
    }


def _value_for_area(
    reports: list[Any],
    area_code: str,
    field: str,
) -> tuple[Any, str | None]:
    for report in reports:
        if not isinstance(report, dict):
            continue
        for series in report.get("timeSeries", []):
            if not isinstance(series, dict):
                continue
            times = series.get("timeDefines")
            if not isinstance(times, list):
                times = []
            for area in series.get("areas", []):
                if not isinstance(area, dict):
                    continue
                area_meta = area.get("area")
                code = area_meta.get("code") if isinstance(area_meta, dict) else None
                if str(code or "") != area_code:
                    continue
                raw = area.get(field)
                if not isinstance(raw, list) or not raw:
                    continue
                for index, item in enumerate(raw):
                    if item in {None, ""}:
                        continue
                    when = times[index] if index < len(times) else (times[0] if times else None)
                    return item, when
    return None, None




def _jma_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _jma_child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    for item in element:
        if _jma_local_name(item.tag) == name:
            return item
    return None


def _jma_children(element: ET.Element | None, name: str) -> list[ET.Element]:
    if element is None:
        return []
    return [item for item in element if _jma_local_name(item.tag) == name]


def _jma_text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = (element.text or "").strip()
    return value or None


def _jma_child_text(element: ET.Element | None, name: str) -> str | None:
    return _jma_text(_jma_child(element, name))


def _jma_descendant(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    return next(
        (item for item in element.iter() if _jma_local_name(item.tag) == name),
        None,
    )


def _jma_desc_text(element: ET.Element | None, name: str) -> str | None:
    return _jma_text(_jma_descendant(element, name))


def _safe_jma_xml_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.data.jma.go.jp"
        or not parsed.path.startswith("/developer/xml/")
    ):
        return None
    return value


def _parse_iso_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _jma_warning_level(name: str | None) -> tuple[str, str]:
    text = str(name or "")
    if "大津波警報" in text:
        return "warning", "extreme"
    if "津波警報" in text:
        return "warning", "severe"
    if "津波注意報" in text:
        return "advisory", "moderate"
    if "解除" in text:
        return "canceled", "minor"
    if "津波予報" in text:
        return "information", "minor"
    return "information", "unknown"


def _jma_height_data(element: ET.Element | None) -> dict[str, Any]:
    if element is None:
        return {}
    tsunami_height = _jma_descendant(element, "TsunamiHeight")
    value = _jma_text(tsunami_height)
    numeric: float | None = None
    if value is not None:
        try:
            numeric = float(value)
        except ValueError:
            numeric = None
    return {
        "value_m": numeric,
        "raw_value": value,
        "description": tsunami_height.attrib.get("description")
        if tsunami_height is not None
        else None,
        "condition": _jma_desc_text(element, "Condition"),
    }


def _jma_report_meta(root: ET.Element) -> dict[str, Any]:
    control = _jma_child(root, "Control")
    head = _jma_child(root, "Head")
    return {
        "control_title": _jma_child_text(control, "Title"),
        "status": _jma_child_text(control, "Status"),
        "publishing_office": _jma_child_text(control, "PublishingOffice"),
        "control_time": _jma_child_text(control, "DateTime"),
        "head_title": _jma_child_text(head, "Title"),
        "report_time": _jma_child_text(head, "ReportDateTime"),
        "target_time": _jma_child_text(head, "TargetDateTime"),
        "event_id": _jma_child_text(head, "EventID"),
        "info_type": _jma_child_text(head, "InfoType"),
        "serial": _jma_child_text(head, "Serial"),
        "headline": _jma_desc_text(_jma_child(head, "Headline"), "Text"),
    }


def _parse_jma_warning_report(payload: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = ET.fromstring(payload)
    meta = _jma_report_meta(root)
    body = _jma_child(root, "Body")
    tsunami = _jma_child(body, "Tsunami")
    forecast = _jma_child(tsunami, "Forecast")
    events: list[dict[str, Any]] = []

    for item in _jma_children(forecast, "Item"):
        area = _jma_child(item, "Area")
        category = _jma_child(item, "Category")
        kind = _jma_child(category, "Kind")
        kind_name = _jma_child_text(kind, "Name")
        alert_level, severity = _jma_warning_level(kind_name)
        area_name = _jma_child_text(area, "Name")
        area_code = _jma_child_text(area, "Code")
        first_height = _jma_child(item, "FirstHeight")
        max_height = _jma_child(item, "MaxHeight")
        canceled = (
            "取消" in str(meta.get("info_type") or "")
            or alert_level == "canceled"
        )
        if canceled:
            continue

        expected_wave = any(
            value is not None and value != ""
            for value in (
                _jma_child_text(first_height, "ArrivalTime"),
                _jma_child_text(first_height, "Condition"),
                _jma_height_data(max_height).get("raw_value"),
                _jma_height_data(max_height).get("description"),
            )
        )
        tsunami_meta = tsunami_semantics(
            "official_tsunami_warning_event",
            alert_stage=alert_level,
            source_alert_level=kind_name,
            active_threat=alert_level in {"warning", "advisory"},
            wave_evidence="expected" if expected_wave else "none",
        )
        events.append(
            {
                "id": (
                    f"jma:{meta.get('event_id') or 'unknown'}:"
                    f"{area_code or area_name or len(events)}:"
                    f"{meta.get('serial') or '0'}"
                ),
                "hazard_type": "tsunami",
                "tsunami_semantics": tsunami_meta,
                "event": kind_name or "津波警報・注意報・予報",
                "headline": (
                    f"{kind_name or '津波情報'} · {area_name}"
                    if area_name
                    else (kind_name or meta.get("head_title") or "津波情報")
                ),
                "severity": severity,
                "urgency": "immediate" if alert_level == "warning" else "expected",
                "certainty": "likely",
                "status": "actual",
                "message_type": str(meta.get("info_type") or "alert"),
                "sent": meta.get("report_time") or meta.get("control_time"),
                "effective": meta.get("target_time"),
                "onset": _jma_child_text(first_height, "ArrivalTime"),
                "expires": None,
                "ends": None,
                "area_desc": area_name,
                "geometry": None,
                "description": meta.get("headline"),
                "instruction": None,
                "sender_name": meta.get("publishing_office")
                or "Japan Meteorological Agency",
                "response": "monitor",
                "affected_zones": [area_code] if area_code else [],
                "parameters": {
                    "alert_level": alert_level,
                    "jma_area_code": area_code,
                    "expected_first_wave": {
                        "arrival_time": _jma_child_text(first_height, "ArrivalTime"),
                        "condition": _jma_child_text(first_height, "Condition"),
                    },
                    "expected_max_height": _jma_height_data(max_height),
                    "event_id": meta.get("event_id"),
                    "serial": meta.get("serial"),
                    "info_type": meta.get("info_type"),
                    "control_title": meta.get("control_title"),
                },
                "web_url": "https://www.jma.go.jp/bosai/map.html#contents=tsunami",
            }
        )
    return meta, events


def _parse_jma_observation_report(
    payload: bytes,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = ET.fromstring(payload)
    meta = _jma_report_meta(root)
    body = _jma_child(root, "Body")
    tsunami = _jma_child(body, "Tsunami")
    observation = _jma_child(tsunami, "Observation")
    events: list[dict[str, Any]] = []

    for item in _jma_children(observation, "Item"):
        area = _jma_child(item, "Area")
        area_name = _jma_child_text(area, "Name")
        area_code = _jma_child_text(area, "Code")
        stations = _jma_children(item, "Station")
        if not stations:
            stations = [item]

        for station in stations:
            station_name = _jma_child_text(station, "Name") or area_name
            station_code = _jma_child_text(station, "Code")
            first_height = _jma_child(station, "FirstHeight")
            max_height = _jma_child(station, "MaxHeight")
            max_data = _jma_height_data(max_height)
            first_time = _jma_child_text(first_height, "ArrivalTime")
            max_time = _jma_child_text(max_height, "DateTime")
            if not any(
                value is not None
                for value in (
                    first_time,
                    max_time,
                    max_data.get("raw_value"),
                    max_data.get("description"),
                )
            ):
                continue

            tsunami_meta = tsunami_semantics(
                "tsunami_observation_event",
                wave_evidence="observed",
            )
            events.append(
                {
                    "id": (
                        f"jma-observation:{meta.get('event_id') or 'unknown'}:"
                        f"{station_code or area_code or station_name or len(events)}:"
                        f"{meta.get('serial') or '0'}"
                    ),
                    "hazard_type": "tsunami",
                    "tsunami_semantics": tsunami_meta,
                    "event": "Tsunami Observation",
                    "headline": (
                        f"Tsunami-Beobachtung · {station_name}"
                        if station_name
                        else "Tsunami-Beobachtung"
                    ),
                    "severity": "unknown",
                    "urgency": "immediate",
                    "certainty": "observed",
                    "status": "actual",
                    "message_type": str(meta.get("info_type") or "update"),
                    "sent": meta.get("report_time") or meta.get("control_time"),
                    "effective": first_time or max_time,
                    "onset": first_time,
                    "expires": None,
                    "ends": None,
                    "area_desc": area_name,
                    "geometry": None,
                    "description": meta.get("headline"),
                    "instruction": None,
                    "sender_name": meta.get("publishing_office")
                    or "Japan Meteorological Agency",
                    "response": "monitor",
                    "affected_zones": [
                        code for code in (area_code, station_code) if code
                    ],
                    "parameters": {
                        "alert_level": "observation",
                        "jma_area_code": area_code,
                        "jma_station_code": station_code,
                        "first_wave_arrival_time": first_time,
                        "first_wave_condition": _jma_child_text(
                            first_height,
                            "Condition",
                        ),
                        "max_wave_time": max_time,
                        "observed_max_height": max_data,
                        "event_id": meta.get("event_id"),
                        "serial": meta.get("serial"),
                        "info_type": meta.get("info_type"),
                    },
                    "web_url": "https://www.jma.go.jp/bosai/map.html#contents=tsunami",
                }
            )
    return meta, events


class JmaProvider:
    """JMA website forecast feed adapter for Japan."""

    id = "jma"
    name = "JMA · Japan Meteorological Agency"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Die Japan Meteorological Agency veröffentlicht regionale Wettervorhersagen "
                "über die JMA-Webdatenfeeds. WeatherRouter ordnet einen Punkt automatisch "
                "der nächstgelegenen zugehörigen AMeDAS-Station und Vorhersageregion zu."
            ),
            coverage="Japan",
            strengths=(
                "offizielle JMA-Quelle",
                "regionale Wetter-, Niederschlags- und Temperaturvorhersagen",
                "automatische Gebietszuordnung",
            ),
            limitations=(
                "die verwendeten JSON-Webfeeds sind operative JMA-Webdaten und nicht dieselbe "
                "Stabilitätszusage wie die formale JMA-XML-Verteilung",
                "nur Japan",
            ),
            documentation_url="https://www.data.jma.go.jp/developer/",
            attribution="Japan Meteorological Agency",
            services=(
                {
                    "name": "Regional Forecast",
                    "status": "integriert",
                    "note": "JMA-Webforecast mit AMeDAS-/class10-Zuordnung",
                },
                {
                    "name": "Tsunami Warning / Advisory / Forecast",
                    "status": "integriert",
                    "note": "JMA Bosai XML VTSE41 über öffentliche PULL-Feeds",
                },
                {
                    "name": "Tsunami Information / Observations",
                    "status": "integriert",
                    "note": "JMA Bosai XML VTSE51/VTSE52 über öffentliche PULL-Feeds",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="regional_weather_forecast",
                scheme="https",
                host="www.jma.go.jp",
                port=443,
                target_type="api",
                required=True,
                capabilities=tuple(_POINT_CAPABILITY_MAP),
                note="JMA bosai forecast JSON and area/station constants.",
            ),
            NetworkTargetInfo(
                purpose="tsunami_warning_information",
                scheme="https",
                host="www.data.jma.go.jp",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=(
                    "official_tsunami_warnings_japan",
                    "tsunami_observations_japan",
                ),
                note=(
                    "JMA public Bosai XML PULL feeds eqvol.xml / eqvol_l.xml and "
                    "referenced tsunami telegrams."
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
        requested = list(dict.fromkeys(
            item for item in capability_ids if item in _POINT_CAPABILITY_MAP
        ))
        if not requested:
            return {
                "provider": self.id,
                "provider_name": self.name,
                "source_class": "forecast",
                "values": {},
            }

        lat = float(latitude)
        lon = float(longitude)
        if not (20.0 <= lat <= 50.0 and 120.0 <= lon <= 155.0):
            return _empty_result(requested, "Koordinate liegt außerhalb Japans.")

        session = async_get_clientsession(hass)
        async with session.get(_FORECAST_AREA_URL, headers={"Accept": "application/json"}, timeout=20) as response:
            response.raise_for_status()
            forecast_areas = await response.json()
        async with session.get(_AMEDAS_URL, headers={"Accept": "application/json"}, timeout=20) as response:
            response.raise_for_status()
            stations = await response.json()

        candidates: list[tuple[float, str, str, str]] = []
        if isinstance(forecast_areas, dict) and isinstance(stations, dict):
            for office_code, entries in forecast_areas.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    class10 = str(entry.get("class10") or "")
                    for station_code in entry.get("amedas", []):
                        station = stations.get(str(station_code))
                        if not isinstance(station, dict):
                            continue
                        station_lat = _station_coord(station.get("lat"))
                        station_lon = _station_coord(station.get("lon"))
                        if station_lat is None or station_lon is None:
                            continue
                        candidates.append((
                            _distance_km(lat, lon, station_lat, station_lon),
                            str(office_code),
                            class10,
                            str(station_code),
                        ))

        if not candidates:
            return _empty_result(requested, "JMA-Gebietszuordnung konnte nicht aufgelöst werden.")

        distance, office_code, class10, station_code = min(candidates, key=lambda item: item[0])
        if distance > 350:
            return _empty_result(requested, "Keine passende JMA-Vorhersagestation in Reichweite.")

        forecast_url = f"{_BASE}/bosai/forecast/data/forecast/{office_code}.json"
        async with session.get(forecast_url, headers={"Accept": "application/json"}, timeout=20) as response:
            response.raise_for_status()
            reports = await response.json()
        if not isinstance(reports, list):
            raise ValueError("JMA forecast response is not a list")

        raw_values = {
            "temperature": _value_for_area(reports, station_code, "temps"),
            "precipitation_probability": _value_for_area(reports, class10, "pops"),
            "weather_summary": _value_for_area(reports, class10, "weathers"),
            "weather_code": _value_for_area(reports, class10, "weatherCodes"),
            "wind_summary": _value_for_area(reports, class10, "winds"),
        }

        values: dict[str, Any] = {}
        times: list[str] = []
        for cap in requested:
            raw, when = raw_values[cap]
            if cap in {"temperature", "precipitation_probability"} and raw not in {None, ""}:
                try:
                    raw = float(raw)
                except (TypeError, ValueError):
                    pass
            values[cap] = {
                "value": raw,
                "unit": _POINT_CAPABILITY_MAP[cap].unit,
            }
            if isinstance(when, str):
                times.append(when)

        station_meta = stations.get(station_code) if isinstance(stations, dict) else None
        return {
            "provider": self.id,
            "provider_name": self.name,
            "source_class": "forecast",
            "available": True,
            "coverage_status": "inside_coverage",
            "data_time": min(times) if times else None,
            "office_code": office_code,
            "class10": class10,
            "station": station_meta.get("enName") if isinstance(station_meta, dict) else station_code,
            "station_distance_km": round(distance, 1),
            "values": values,
            "attribution": "Japan Meteorological Agency",
        }


    async def _async_tsunami_entries(
        self,
        hass: HomeAssistant,
    ) -> list[dict[str, str]]:
        session = async_get_clientsession(hass)
        entries: dict[str, dict[str, str]] = {}

        for feed_url in (_JMA_XML_FEED_FAST, _JMA_XML_FEED_LONG):
            async with session.get(
                feed_url,
                headers={"Accept": "application/atom+xml,application/xml,text/xml,*/*"},
                timeout=20,
            ) as response:
                response.raise_for_status()
                payload = await response.read()

            root = ET.fromstring(payload)
            for entry in (
                item for item in root.iter() if _jma_local_name(item.tag) == "entry"
            ):
                title = _jma_child_text(entry, "title") or ""
                if "津波" not in title:
                    continue
                link = _jma_child(entry, "link")
                href = link.attrib.get("href") if link is not None else None
                safe_url = _safe_jma_xml_url(href)
                if safe_url is None:
                    continue
                updated = _jma_child_text(entry, "updated") or ""
                published = _jma_child_text(entry, "published") or updated
                existing = entries.get(safe_url)
                candidate = {
                    "title": title,
                    "url": safe_url,
                    "updated": updated,
                    "published": published,
                }
                if existing is None or updated > existing.get("updated", ""):
                    entries[safe_url] = candidate

        return sorted(
            entries.values(),
            key=lambda item: item.get("updated", ""),
            reverse=True,
        )

    async def _async_jma_tsunami_reports(
        self,
        hass: HomeAssistant,
        *,
        observation: bool,
    ) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
        entries = await self._async_tsunami_entries(hass)
        session = async_get_clientsession(hass)
        reports: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        fetched = 0

        for entry in entries:
            title = entry.get("title", "")
            if observation:
                if "津波情報" not in title:
                    continue
            elif "津波警報" not in title and "津波注意報" not in title:
                continue

            updated = _parse_iso_time(entry.get("updated"))
            if updated is not None and datetime.now(timezone.utc) - updated > timedelta(days=3):
                continue

            async with session.get(
                entry["url"],
                headers={"Accept": "application/xml,text/xml,*/*"},
                timeout=20,
            ) as response:
                response.raise_for_status()
                payload = await response.read()

            if observation:
                report = _parse_jma_observation_report(payload)
            else:
                report = _parse_jma_warning_report(payload)
            reports.append(report)
            fetched += 1
            if fetched >= 16:
                break

        return reports

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
        del latitude, longitude, bbox
        if capability_id not in {
            "official_tsunami_warnings_japan",
            "tsunami_observations_japan",
        }:
            raise ValueError(f"Unsupported JMA hazard capability: {capability_id}")

        observation = capability_id == "tsunami_observations_japan"
        reports = await self._async_jma_tsunami_reports(
            hass,
            observation=observation,
        )
        maximum = max(1, min(int(limit), 1000))
        events: list[dict[str, Any]] = []

        if observation:
            for _meta, report_events in reports:
                events.extend(report_events)
                if len(events) >= maximum:
                    break
        else:
            seen_event_ids: set[str] = set()
            for meta, report_events in reports:
                event_id = str(meta.get("event_id") or meta.get("report_time") or "")
                if event_id in seen_event_ids:
                    continue
                seen_event_ids.add(event_id)
                if "取消" in str(meta.get("info_type") or ""):
                    continue
                events.extend(report_events)
                if len(events) >= maximum:
                    break

        events = events[:maximum]
        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "observation" if observation else "warning",
            "render_mode": "hazard_feed",
            "coverage_status": "regional",
            "events": events,
            "event_count": len(events),
            "provider_metadata": {
                "atom_feeds": [_JMA_XML_FEED_FAST, _JMA_XML_FEED_LONG],
                "relevant_report_count": len(reports),
                "geometry_status": "jma_area_codes_without_embedded_polygons",
            },
            "attribution": "Japan Meteorological Agency",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        selected = capability_id
        if selected is None:
            selected = "official_tsunami_warnings_japan"
        if selected not in {
            "official_tsunami_warnings_japan",
            "tsunami_observations_japan",
        }:
            return {
                "ok": True,
                "stage": "forecast_provider",
                "provider_revision": _PROVIDER_REVISION,
                "note": "Use point diagnostics for the regular JMA forecast capabilities.",
            }

        feed = await self.async_get_hazard_feed(
            hass,
            selected,
            limit=25,
        )
        return {
            "ok": True,
            "stage": "jma_public_xml_pull",
            "provider_revision": _PROVIDER_REVISION,
            "capability": selected,
            "event_count": feed.get("event_count", 0),
            "provider_metadata": feed.get("provider_metadata"),
            "sample": [
                {
                    "headline": item.get("headline"),
                    "severity": item.get("severity"),
                    "certainty": item.get("certainty"),
                    "area_desc": item.get("area_desc"),
                    "parameters": item.get("parameters"),
                }
                for item in feed.get("events", [])[:5]
            ],
        }
