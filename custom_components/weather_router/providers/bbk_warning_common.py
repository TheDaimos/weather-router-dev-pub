"""Shared BBK/NINA warning helpers for WeatherRouter."""

from __future__ import annotations

from math import isfinite
from typing import Any
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .hazard_common import geometry_intersects_bbox, normalize_severity

_BASE_URL = "https://warnung.bund.de/api31"
_HEADERS = {
    "Accept": "application/json,application/geo+json,*/*",
    "User-Agent": "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev)",
}


def _title(item: dict[str, Any]) -> str:
    translated = item.get("i18nTitle")
    if isinstance(translated, dict):
        for language in ("de", "en"):
            value = translated.get(language)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(item.get("headline") or item.get("event") or "Amtliche Warnmeldung").strip()


def _hazard_type_for_title(title: str, *, police: bool) -> str:
    if police:
        return "public_safety"
    text = title.casefold()
    patterns = (
        ("explosive_ordnance", ("bombenfund", "weltkriegsbombe", "kampfmittel", "munition")),
        ("fire", ("großbrand", "brand ", "feuer", "rauchentwicklung")),
        ("infrastructure_outage", ("stromausfall", "stromversorgung", "gasausfall", "wasserversorgung")),
        ("contamination", ("trinkwasser", "verunreinigung", "kontamination", "geruchsbelästigung")),
        ("cbrn", ("radioaktiv", "chemisch", "biologisch", "gefahrstoff", "cbrn")),
        ("evacuation", ("evakuierung", "evakuier", "räumung")),
        ("levee_failure", ("deichbruch", "deichversagen")),
        ("dam_failure", ("dammbruch", "talsperrenbruch", "talsperrenversagen")),
        (
            "glacial_lake_outburst_flood",
            ("glacial lake outburst flood", "glof", "gletscherseeausbruch", "gletschersee-ausbruch"),
        ),
        (
            "ice_jam_flood",
            ("ice jam flood", "ice jam", "eisstau-hochwasser", "eisstau"),
        ),
        ("debris_flow", ("mure", "schlammlawine", "schlammstrom", "geröllstrom")),
        ("surface_water_flood", ("oberflächenüberflutung", "pluviales hochwasser", "straßenüberflutung")),
        ("flash_flood", ("sturzflut", "plötzliche überschwemmung")),
        ("flood", ("hochwasser", "überschwemm", "überflutung", "pegel")),
    )
    for hazard_type, needles in patterns:
        if any(needle in text for needle in needles):
            return hazard_type
    return "civil_protection"


def _geometry_from_geojson(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    if kind == "Feature" and isinstance(payload.get("geometry"), dict):
        return payload["geometry"]
    if kind == "FeatureCollection":
        features = payload.get("features")
        if isinstance(features, list):
            geometries = [
                feature.get("geometry")
                for feature in features
                if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict)
            ]
            if len(geometries) == 1:
                return geometries[0]
            polygons: list[Any] = []
            points: list[Any] = []
            for geometry in geometries:
                if geometry.get("type") == "Polygon" and isinstance(geometry.get("coordinates"), list):
                    polygons.append(geometry["coordinates"])
                elif geometry.get("type") == "MultiPolygon" and isinstance(geometry.get("coordinates"), list):
                    polygons.extend(geometry["coordinates"])
                elif geometry.get("type") == "Point" and isinstance(geometry.get("coordinates"), list):
                    points.append(geometry["coordinates"])
            if polygons:
                return {"type": "MultiPolygon", "coordinates": polygons}
            if points:
                if len(points) == 1:
                    return {"type": "Point", "coordinates": points[0]}
                return {"type": "MultiPoint", "coordinates": points}
        return None
    if kind in {
        "Point", "MultiPoint", "LineString", "MultiLineString",
        "Polygon", "MultiPolygon", "GeometryCollection",
    }:
        return payload
    return None


def _valid_geometry(geometry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(geometry, dict):
        return None
    coordinates = geometry.get("coordinates")
    if coordinates is None and geometry.get("type") != "GeometryCollection":
        return None

    def validate(value: Any) -> bool:
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            longitude = float(value[0])
            latitude = float(value[1])
            return (
                isfinite(longitude)
                and isfinite(latitude)
                and -180 <= longitude <= 180
                and -90 <= latitude <= 90
            )
        if isinstance(value, (list, tuple)):
            return all(validate(item) for item in value)
        return False

    if coordinates is not None and not validate(coordinates):
        return None
    return geometry


async def _fetch_json(hass: HomeAssistant, path: str) -> Any:
    session = async_get_clientsession(hass)
    async with session.get(
        f"{_BASE_URL}{path}",
        headers=_HEADERS,
        timeout=20,
    ) as response:
        response.raise_for_status()
        return await response.json(content_type=None)


async def fetch_bbk_feed(
    hass: HomeAssistant,
    *,
    map_path: str,
    provider_id: str,
    provider_name: str,
    provider_revision: str,
    capability_id: str,
    channel: str,
    event_label: str = "Civil protection warning",
    source_semantics: str = "official_warning",
    bbox: tuple[float, float, float, float] | None,
    limit: int,
) -> dict[str, Any]:
    """Fetch one public warnung.bund.de map feed and resolve its geometries."""
    police = channel == "police"
    raw = await _fetch_json(hass, map_path)
    if not isinstance(raw, list):
        raise ValueError("BBK mapData response is not a list")

    maximum = max(1, min(int(limit), 200))
    active = [
        item for item in raw
        if isinstance(item, dict)
        and str(item.get("type") or "").casefold() not in {"cancel", "cancelled"}
    ][:maximum]

    events: list[dict[str, Any]] = []
    geometry_errors = 0
    for item in active:
        identifier = str(item.get("id") or "").strip()
        if not identifier:
            continue
        geometry = None
        try:
            geo_payload = await _fetch_json(
                hass,
                f"/warnings/{quote(identifier, safe='')}.geojson",
            )
            geometry = _valid_geometry(_geometry_from_geojson(geo_payload))
        except Exception:  # noqa: BLE001 - geometry enrichment is best-effort
            geometry_errors += 1

        if not geometry_intersects_bbox(geometry, bbox):
            continue

        title = _title(item)
        raw_severity = str(item.get("severity") or "unknown")
        severity = normalize_severity(raw_severity)
        message_type = str(item.get("type") or "Alert").casefold()
        trans_keys = item.get("transKeys")
        if not isinstance(trans_keys, dict):
            trans_keys = {}

        events.append(
            {
                "id": identifier,
                "hazard_type": _hazard_type_for_title(title, police=police),
                "event": event_label,
                "headline": title,
                "severity": severity,
                "urgency": str(item.get("urgency") or "unknown").casefold(),
                "certainty": "unknown",
                "status": "actual",
                "message_type": message_type,
                # NINA mapData.startDate ist Warnbeginn, keine belegte Ausstellungszeit.
                "sent": None,
                "effective": item.get("startDate"),
                "onset": item.get("startDate"),
                "expires": item.get("expiresDate"),
                "ends": item.get("expiresDate"),
                "area_desc": None,
                "geometry": geometry,
                "description": None,
                "instruction": None,
                "sender_name": "BBK / warnung.bund.de",
                "response": "monitor",
                "affected_zones": [],
                "source_semantics": source_semantics,
                "parameters": {
                    "bbk_event_code": trans_keys.get("event"),
                    "bbk_version": item.get("version"),
                    "bbk_message_type": item.get("type"),
                    "source_channel": channel,
                    "classification_note": (
                        "Official police warning; WeatherRouter does not infer attack/terrorism."
                        if police
                        else "Official civil-protection warning; source wording is preserved."
                    ),
                },
                "web_url": "https://warnung.bund.de/",
            }
        )

    return {
        "provider": provider_id,
        "provider_name": provider_name,
        "provider_revision": provider_revision,
        "capability": capability_id,
        "source_class": "official_warning",
        "render_mode": "hazard_feed",
        "coverage_status": "viewport_filtered" if bbox is not None else "germany",
        "events": events,
        "event_count": len(events),
        "provider_metadata": {
            "official_warning": True,
            "source": "warnung.bund.de / NINA",
            "source_channel": channel,
            "map_items": len(raw),
            "active_items_considered": len(active),
            "geometry_errors": geometry_errors,
            "bbox_filtered": bbox is not None,
        },
        "attribution": "Bundesamt für Bevölkerungsschutz und Katastrophenhilfe (BBK) · warnung.bund.de",
    }
