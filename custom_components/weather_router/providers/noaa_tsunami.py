"""NOAA U.S. Tsunami Warning Centers official CAP hazard provider."""

from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .hazard_common import normalize_severity, tsunami_semantics

_PROVIDER_REVISION = "wr-0.10.129-tsunami-semantics-1"
_SOURCES = (
    {
        "id": "ntwc",
        "name": "National Tsunami Warning Center",
        "cap_url": "https://www.tsunami.gov/events/xml/PAAQCAP.xml",
        "atom_url": "https://www.tsunami.gov/events/xml/PAAQAtom.xml",
        "coverage": "Kontinentale USA, Alaska und Kanada",
    },
    {
        "id": "ptwc",
        "name": "Pacific Tsunami Warning Center",
        "cap_url": "https://www.tsunami.gov/events/xml/PHEBCAP.xml",
        "atom_url": "https://www.tsunami.gov/events/xml/PHEBAtom.xml",
        "coverage": (
            "Hawaii, US-Pazifik-/Karibikgebiete sowie internationale "
            "Pazifik-/Karibik-Tsunamiinformationsdienste"
        ),
    },
)

_CAPABILITIES = (
    CapabilityInfo(
        id="official_tsunami_alerts",
        name="Amtliche Tsunamiwarnungen · NOAA NTWC/PTWC",
        unit=None,
        source_class="warning",
        render_mode="hazard_feed",
        description=(
            "Aktuelle amtliche CAP-1.2-Tsunamimeldungen der US Tsunami Warning Centers."
        ),
        coverage="NTWC + PTWC Zuständigkeitsgebiete",
        temporal_resolution="ereignisgesteuert",
        strengths=(
            "amtliche NOAA/NWS-Tsunamiwarnzentren",
            "CAP-TSU / CAP 1.2",
            "Warning, Advisory, Watch, Threat und Information sauber unterscheidbar",
        ),
        limitations=(
            "keine alleinige weltweite Zuständigkeit; nationale Warnzentren bleiben maßgeblich",
        ),
        documentation_url="https://www.tsunami.gov/?page=productRetrieval",
    ),
)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    for item in element:
        if _local_name(item.tag) == name:
            return item
    return None


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [item for item in element if _local_name(item.tag) == name]


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = (element.text or "").strip()
    return value or None


def _child_text(element: ET.Element, name: str) -> str | None:
    return _text(_child(element, name))


def _select_info(alert: ET.Element) -> ET.Element | None:
    infos = _children(alert, "info")
    if not infos:
        return None
    for info in infos:
        language = (_child_text(info, "language") or "").casefold()
        if language in {"en-us", "en"}:
            return info
    return infos[0]


def _parameter_map(info: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in _children(info, "parameter"):
        name = _child_text(item, "valueName")
        value = _child_text(item, "value")
        if name and value is not None:
            result[name] = value
    return result


def _geocode_map(area: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _children(area, "geocode"):
        name = _child_text(item, "valueName")
        value = _child_text(item, "value")
        if name and value is not None:
            result[name] = value
    return result


def _polygon_geometry(areas: list[ET.Element]) -> dict[str, Any] | None:
    polygons: list[list[list[float]]] = []
    for area in areas:
        for polygon in _children(area, "polygon"):
            raw = _text(polygon)
            if not raw:
                continue
            ring: list[list[float]] = []
            valid = True
            for pair in raw.split():
                bits = pair.split(",")
                if len(bits) != 2:
                    valid = False
                    break
                try:
                    latitude = float(bits[0])
                    longitude = float(bits[1])
                except ValueError:
                    valid = False
                    break
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    valid = False
                    break
                ring.append([longitude, latitude])
            if not valid or len(ring) < 3:
                continue
            if ring[0] != ring[-1]:
                ring.append(list(ring[0]))
            polygons.append([ring])

    if not polygons:
        return None
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def _alert_level(*values: Any) -> str:
    text = " ".join(str(value or "") for value in values).casefold()
    if "no tsunami warning" in text or "no tsunami threat" in text:
        return "no_threat"
    if "warning" in text:
        return "warning"
    if "advisory" in text:
        return "advisory"
    if "watch" in text:
        return "watch"
    if "threat" in text:
        return "threat"
    if "information" in text or "statement" in text:
        return "information"
    return "information"


def _derived_severity(level: str) -> str:
    return {
        "warning": "extreme",
        "advisory": "severe",
        "threat": "severe",
        "watch": "moderate",
        "information": "minor",
        "no_threat": "minor",
    }.get(level, "unknown")


def _parse_cap(payload: bytes, source: dict[str, str]) -> dict[str, Any]:
    root = ET.fromstring(payload)
    alert = root if _local_name(root.tag) == "alert" else next(
        (item for item in root.iter() if _local_name(item.tag) == "alert"),
        None,
    )
    if alert is None:
        raise ValueError("NOAA tsunami CAP document has no alert element")

    info = _select_info(alert)
    if info is None:
        raise ValueError("NOAA tsunami CAP document has no info element")

    areas = _children(info, "area")
    event = _child_text(info, "event")
    headline = _child_text(info, "headline")
    description = _child_text(info, "description")
    instruction = _child_text(info, "instruction")
    level = _alert_level(event, headline, description)
    status = _child_text(alert, "status") or "Unknown"
    message_type = _child_text(alert, "msgType") or "Unknown"
    cap_severity = normalize_severity(_child_text(info, "severity"))
    severity = cap_severity if cap_severity != "unknown" else _derived_severity(level)

    area_descriptions = [
        value
        for value in (_child_text(area, "areaDesc") for area in areas)
        if value
    ]
    geocodes: dict[str, dict[str, str]] = {}
    circles: list[str] = []
    for index, area in enumerate(areas):
        codes = _geocode_map(area)
        if codes:
            geocodes[str(index)] = codes
        circles.extend(
            raw
            for raw in (_text(item) for item in _children(area, "circle"))
            if raw
        )

    actual = status.casefold() == "actual"
    canceled = message_type.casefold() == "cancel"
    active_threat = actual and not canceled and level in {
        "warning",
        "advisory",
        "watch",
        "threat",
    }

    return {
        "id": _child_text(alert, "identifier") or f"{source['id']}:current",
        "hazard_type": "tsunami",
        "tsunami_semantics": tsunami_semantics(
            "official_tsunami_warning_event",
            alert_stage=level,
            source_alert_level=event,
            active_threat=active_threat,
            wave_evidence="none",
        ),
        "event": event or "Tsunami Message",
        "headline": headline or event or "Tsunami Message",
        "severity": severity,
        "urgency": (_child_text(info, "urgency") or "unknown").casefold(),
        "certainty": (_child_text(info, "certainty") or "unknown").casefold(),
        "status": status.casefold(),
        "message_type": message_type.casefold(),
        "sent": _child_text(alert, "sent"),
        "effective": _child_text(info, "effective"),
        "onset": _child_text(info, "onset"),
        "expires": _child_text(info, "expires"),
        "ends": None,
        "area_desc": "; ".join(area_descriptions) or source["coverage"],
        "geometry": _polygon_geometry(areas),
        "description": description,
        "instruction": instruction,
        "sender_name": _child_text(info, "senderName") or source["name"],
        "response": _child_text(info, "responseType"),
        "affected_zones": area_descriptions,
        "parameters": {
            "alert_level": level,
            "active_threat": active_threat,
            "center": source["id"],
            "center_name": source["name"],
            "coverage": source["coverage"],
            "cap_parameters": _parameter_map(info),
            "geocodes": geocodes,
            "circles": circles,
        },
        "web_url": _child_text(info, "web") or "https://www.tsunami.gov/",
        "active_threat": active_threat,
        "alert_level": level,
    }


class NoaaTsunamiProvider:
    """Official current CAP messages from NTWC and PTWC."""

    id = "noaa_tsunami"
    name = "NOAA · U.S. Tsunami Warning Centers"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "NTWC und PTWC veröffentlichen aktuelle Tsunamimeldungen als "
                "CAP-1.2/CAP-TSU sowie Atom-Feeds."
            ),
            coverage="NTWC- und PTWC-Zuständigkeitsgebiete",
            strengths=(
                "amtliche NOAA/NWS-Warnzentren",
                "maschinenlesbares CAP",
                "Warning/Advisory/Watch/Threat/Information",
            ),
            limitations=(
                "nationale und regionale Tsunamiwarnzentren außerhalb der NOAA-Zuständigkeit "
                "müssen zusätzlich berücksichtigt werden",
            ),
            documentation_url="https://www.tsunami.gov/?page=productRetrieval",
            attribution="NOAA / National Weather Service · U.S. Tsunami Warning System",
            services=(
                {
                    "name": "NTWC CAP / Atom",
                    "status": "integriert",
                    "note": "aktuelle Tsunamimeldung für NTWC-Zuständigkeit",
                },
                {
                    "name": "PTWC CAP / Atom",
                    "status": "integriert",
                    "note": "aktuelle Tsunamimeldung für PTWC-Zuständigkeit",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="official_tsunami_alerts",
                scheme="https",
                host="www.tsunami.gov",
                port=443,
                target_type="hazard_feed",
                required=True,
                capabilities=("official_tsunami_alerts",),
                note="NTWC/PTWC CAP-TSU/CAP 1.2 and Atom feeds.",
            ),
        )

    async def _async_messages(self, hass: HomeAssistant) -> list[dict[str, Any]]:
        session = async_get_clientsession(hass)
        messages: list[dict[str, Any]] = []
        errors: list[str] = []
        for source in _SOURCES:
            try:
                async with session.get(
                    source["cap_url"],
                    headers={"Accept": "application/xml,text/xml,*/*"},
                    timeout=20,
                ) as response:
                    response.raise_for_status()
                    payload = await response.read()
                messages.append(_parse_cap(payload, source))
            except Exception as err:  # noqa: BLE001 - one warning center must not mask the other
                errors.append(f"{source['id']}:{type(err).__name__}:{err}")

        if not messages:
            raise ValueError(
                "NOAA tsunami warning centers unavailable"
                + (f" ({'; '.join(errors)})" if errors else "")
            )
        for message in messages:
            message["provider_errors"] = list(errors)
        return messages

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
        if capability_id != "official_tsunami_alerts":
            raise ValueError(f"Unsupported NOAA tsunami capability: {capability_id}")

        messages = await self._async_messages(hass)
        active = [item for item in messages if item.get("active_threat") is True]
        maximum = max(1, min(int(limit), 100))
        events = active[:maximum]

        return {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "warning",
            "render_mode": "hazard_feed",
            "coverage_status": "multi_region",
            "events": events,
            "event_count": len(events),
            "provider_metadata": {
                "latest_center_messages": [
                    {
                        "id": item.get("id"),
                        "center": (item.get("parameters") or {}).get("center"),
                        "headline": item.get("headline"),
                        "alert_level": item.get("alert_level"),
                        "active_threat": item.get("active_threat"),
                        "sent": item.get("sent"),
                        "status": item.get("status"),
                        "message_type": item.get("message_type"),
                    }
                    for item in messages
                ]
            },
            "attribution": "NOAA / National Weather Service · U.S. Tsunami Warning System",
        }

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id not in {None, "official_tsunami_alerts"}:
            return {
                "ok": False,
                "stage": "capability_selection",
                "provider_revision": _PROVIDER_REVISION,
            }
        feed = await self.async_get_hazard_feed(
            hass,
            "official_tsunami_alerts",
            limit=10,
        )
        return {
            "ok": True,
            "stage": "cap_tsu_current",
            "provider_revision": _PROVIDER_REVISION,
            "active_alert_count": feed.get("event_count", 0),
            "latest_center_messages": (feed.get("provider_metadata") or {}).get(
                "latest_center_messages",
                [],
            ),
        }
