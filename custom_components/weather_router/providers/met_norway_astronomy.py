"""MET Norway Sunrise 3.0 astronomy provider for WeatherRouter."""

from __future__ import annotations

from datetime import datetime, timezone
from math import cos, pi
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_BASE = "https://api.met.no/weatherapi/sunrise/3.0"
_MOON_URL = f"{_BASE}/moon"
_SUN_URL = f"{_BASE}/sun"
_USER_AGENT = "WeatherRouter/0.10 (https://github.com/TheDaimos)"
_SYNODIC_MONTH_DAYS = 29.53058867

_MOON_CAPABILITIES = (
    CapabilityInfo(
        "moon_phase_angle",
        "Mondphase · Winkel",
        "°",
        "astronomy",
        "value",
        "Astronomischer Phasenwinkel: 0° Neumond, 180° Vollmond.",
        "Global",
        "täglich",
        None,
        ("JPL-/Skyfield-basierte MET-Norway-Berechnung",),
        (),
        "https://api.met.no/weatherapi/sunrise/3.0/documentation",
    ),
    CapabilityInfo("moon_phase_name", "Mondphase · Bezeichnung", None, "astronomy", "value",
        "Aus dem MET-Norway-Phasenwinkel abgeleitete Phasenbezeichnung.", "Global", "täglich"),
    CapabilityInfo("moon_illumination", "Mond · beleuchteter Anteil", "%", "astronomy", "value",
        "Aus dem Phasenwinkel berechneter beleuchteter Anteil der Mondscheibe.", "Global", "täglich"),
    CapabilityInfo("moon_age_days", "Mondalter", "Tage", "astronomy", "value",
        "Aus dem Phasenwinkel abgeleitetes Alter innerhalb des synodischen Monats.", "Global", "täglich"),
    CapabilityInfo("moonrise_time", "Mondaufgang · Zeit", None, "astronomy", "value",
        "Mondaufgang am angefragten Ort; kann in Polar-/Sonderlagen fehlen.", "Global", "täglich"),
    CapabilityInfo("moonrise_azimuth", "Mondaufgang · Azimut", "°", "astronomy", "value",
        "Azimut des Mondaufgangs.", "Global", "täglich"),
    CapabilityInfo("moonset_time", "Monduntergang · Zeit", None, "astronomy", "value",
        "Monduntergang am angefragten Ort; kann in Polar-/Sonderlagen fehlen.", "Global", "täglich"),
    CapabilityInfo("moonset_azimuth", "Monduntergang · Azimut", "°", "astronomy", "value",
        "Azimut des Monduntergangs.", "Global", "täglich"),
    CapabilityInfo("high_moon_time", "Mondhöchststand · Zeit", None, "astronomy", "value",
        "Zeit des Meridiandurchgangs des Mondes.", "Global", "täglich"),
    CapabilityInfo("high_moon_elevation", "Mondhöchststand · Höhe", "°", "astronomy", "value",
        "Höhe des Mondzentrums beim höchsten Tagesstand.", "Global", "täglich"),
    CapabilityInfo("high_moon_visible", "Mondhöchststand · sichtbar", None, "astronomy", "value",
        "Ob der Mond beim höchsten Tagesstand über dem Horizont steht.", "Global", "täglich"),
    CapabilityInfo("low_moon_time", "Mondtiefststand · Zeit", None, "astronomy", "value",
        "Zeit des Antimeridiandurchgangs des Mondes.", "Global", "täglich"),
    CapabilityInfo("low_moon_elevation", "Mondtiefststand · Höhe", "°", "astronomy", "value",
        "Höhe des Mondzentrums beim tiefsten Tagesstand.", "Global", "täglich"),
    CapabilityInfo("low_moon_visible", "Mondtiefststand · sichtbar", None, "astronomy", "value",
        "Ob der Mond beim tiefsten Tagesstand über dem Horizont steht.", "Global", "täglich"),
)

_SUN_CAPABILITIES = (
    CapabilityInfo("sunrise_time", "Sonnenaufgang · Zeit", None, "astronomy", "value",
        "Sonnenaufgang am angefragten Ort.", "Global", "täglich"),
    CapabilityInfo("sunrise_azimuth", "Sonnenaufgang · Azimut", "°", "astronomy", "value",
        "Azimut des Sonnenaufgangs.", "Global", "täglich"),
    CapabilityInfo("sunset_time", "Sonnenuntergang · Zeit", None, "astronomy", "value",
        "Sonnenuntergang am angefragten Ort.", "Global", "täglich"),
    CapabilityInfo("sunset_azimuth", "Sonnenuntergang · Azimut", "°", "astronomy", "value",
        "Azimut des Sonnenuntergangs.", "Global", "täglich"),
    CapabilityInfo("solar_noon_time", "Sonnenhöchststand · Zeit", None, "astronomy", "value",
        "Zeit des Meridiandurchgangs der Sonne.", "Global", "täglich"),
    CapabilityInfo("solar_noon_elevation", "Sonnenhöchststand · Höhe", "°", "astronomy", "value",
        "Höhe des Sonnenzentrums beim Tageshöchststand.", "Global", "täglich"),
    CapabilityInfo("solar_noon_visible", "Sonnenhöchststand · sichtbar", None, "astronomy", "value",
        "Ob die Sonne beim Tageshöchststand über dem Horizont steht.", "Global", "täglich"),
    CapabilityInfo("solar_midnight_time", "Sonnentiefststand · Zeit", None, "astronomy", "value",
        "Zeit des Antimeridiandurchgangs der Sonne.", "Global", "täglich"),
    CapabilityInfo("solar_midnight_elevation", "Sonnentiefststand · Höhe", "°", "astronomy", "value",
        "Höhe des Sonnenzentrums beim Tagestiefststand.", "Global", "täglich"),
    CapabilityInfo("solar_midnight_visible", "Sonnentiefststand · sichtbar", None, "astronomy", "value",
        "Ob die Sonne beim Tagestiefststand über dem Horizont steht.", "Global", "täglich"),
)

_CAPABILITIES = _MOON_CAPABILITIES + _SUN_CAPABILITIES
_MOON_IDS = {item.id for item in _MOON_CAPABILITIES}
_SUN_IDS = {item.id for item in _SUN_CAPABILITIES}


def _phase_name(angle: float) -> str:
    normalized = angle % 360.0
    if normalized < 1.0 or normalized >= 359.0:
        return "Neumond"
    if normalized < 90.0:
        return "Zunehmende Sichel"
    if normalized < 91.0:
        return "Erstes Viertel"
    if normalized < 179.0:
        return "Zunehmender Mond"
    if normalized < 181.0:
        return "Vollmond"
    if normalized < 270.0:
        return "Abnehmender Mond"
    if normalized < 271.0:
        return "Letztes Viertel"
    return "Abnehmende Sichel"


def _nested(properties: dict[str, Any], block: str, field: str) -> Any:
    value = properties.get(block)
    if not isinstance(value, dict):
        return None
    return value.get(field)


class MetNorwayAstronomyProvider:
    """Worldwide sun/moon calculations from MET Norway Sunrise 3.0."""

    id = "met_norway_astronomy"
    name = "MET Norway · Sonne & Mond"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "MET Norway Sunrise 3.0 berechnet weltweite Sonnen- und Mondereignisse "
                "für einen expliziten Punkt auf der Erde."
            ),
            coverage="Global",
            strengths=(
                "weltweite astronomische Berechnung",
                "Mondphase und lokale Auf-/Untergangszeiten",
                "Höchst-/Tiefststände mit Sichtbarkeit",
                "offene MET-Norway-WeatherAPI",
            ),
            limitations=(
                "astronomische Sichtbarkeit bedeutet über/unter Horizont, nicht wolkenfreie Sicht",
                "Mondaufgang/-untergang oder Meridiandurchgänge können an einzelnen Tagen fehlen",
                "nächster Voll-/Neumond wird nicht aus Tageswerten hochgerechnet",
            ),
            documentation_url="https://api.met.no/weatherapi/sunrise/3.0/documentation",
            attribution="Meteorologisk institutt / MET Norway",
            services=(
                {"name": "Moon 3.0", "status": "integriert", "note": "Mondphase, Auf-/Untergang, höchste/niedrigste Position"},
                {"name": "Sun 3.0", "status": "integriert", "note": "Sonnenauf-/untergang, höchste/niedrigste Position"},
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="astronomy_sun_moon",
                scheme="https",
                host="api.met.no",
                port=443,
                target_type="api",
                required=True,
                capabilities=tuple(item.id for item in _CAPABILITIES),
                note="MET Norway Sunrise 3.0; serverseitiger identifizierender User-Agent.",
            ),
        )

    async def _fetch(
        self,
        hass: HomeAssistant,
        url: str,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:
        session = async_get_clientsession(hass)
        async with session.get(
            url,
            params={
                "lat": round(latitude, 6),
                "lon": round(longitude, 6),
                "date": datetime.now(timezone.utc).date().isoformat(),
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=15,
        ) as response:
            response.raise_for_status()
            payload = await response.json()
        return payload if isinstance(payload, dict) else {}

    async def async_fetch_point(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        capability_ids: list[str],
    ) -> dict[str, Any]:
        requested = list(dict.fromkeys(item for item in capability_ids if item in {cap.id for cap in _CAPABILITIES}))
        if not requested:
            return {
                "provider": self.id,
                "provider_name": self.name,
                "source_class": "astronomy",
                "values": {},
            }

        moon_payload: dict[str, Any] = {}
        sun_payload: dict[str, Any] = {}
        if any(item in _MOON_IDS for item in requested):
            moon_payload = await self._fetch(hass, _MOON_URL, latitude, longitude)
        if any(item in _SUN_IDS for item in requested):
            sun_payload = await self._fetch(hass, _SUN_URL, latitude, longitude)

        moon_props = moon_payload.get("properties") if isinstance(moon_payload.get("properties"), dict) else {}
        sun_props = sun_payload.get("properties") if isinstance(sun_payload.get("properties"), dict) else {}
        phase_raw = _nested(moon_props, "moonphase", "value")
        phase = float(phase_raw) if isinstance(phase_raw, (int, float)) else None
        phase_required = {
            "moon_phase_angle",
            "moon_phase_name",
            "moon_illumination",
            "moon_age_days",
        }
        if phase is None and any(item in phase_required for item in requested):
            return {
                "provider": self.id,
                "provider_name": self.name,
                "source_class": "astronomy",
                "available": False,
                "unavailable_code": "temporarily_unavailable",
                "reason": "MET Norway lieferte aktuell keinen nutzbaren Mondphasenwinkel.",
                "latitude": latitude,
                "longitude": longitude,
            }

        moon_values: dict[str, dict[str, Any]] = {
            "moon_phase_angle": {"value": phase, "unit": "°", "field": "moonphase.value"},
            "moon_phase_name": {"value": _phase_name(phase) if phase is not None else None, "unit": None, "field": "moonphase.value"},
            "moon_illumination": {
                "value": round((1.0 - cos((phase or 0.0) * pi / 180.0)) * 50.0, 2) if phase is not None else None,
                "unit": "%",
                "field": "derived_from_moonphase",
            },
            "moon_age_days": {
                "value": round(((phase or 0.0) % 360.0) / 360.0 * _SYNODIC_MONTH_DAYS, 2) if phase is not None else None,
                "unit": "Tage",
                "field": "derived_from_moonphase",
            },
            "moonrise_time": {"value": _nested(moon_props, "moonrise", "time"), "unit": None, "field": "moonrise.time"},
            "moonrise_azimuth": {"value": _nested(moon_props, "moonrise", "azimuth"), "unit": "°", "field": "moonrise.azimuth"},
            "moonset_time": {"value": _nested(moon_props, "moonset", "time"), "unit": None, "field": "moonset.time"},
            "moonset_azimuth": {"value": _nested(moon_props, "moonset", "azimuth"), "unit": "°", "field": "moonset.azimuth"},
            "high_moon_time": {"value": _nested(moon_props, "high_moon", "time"), "unit": None, "field": "high_moon.time"},
            "high_moon_elevation": {"value": _nested(moon_props, "high_moon", "disc_centre_elevation"), "unit": "°", "field": "high_moon.disc_centre_elevation"},
            "high_moon_visible": {"value": _nested(moon_props, "high_moon", "visible"), "unit": None, "field": "high_moon.visible"},
            "low_moon_time": {"value": _nested(moon_props, "low_moon", "time"), "unit": None, "field": "low_moon.time"},
            "low_moon_elevation": {"value": _nested(moon_props, "low_moon", "disc_centre_elevation"), "unit": "°", "field": "low_moon.disc_centre_elevation"},
            "low_moon_visible": {"value": _nested(moon_props, "low_moon", "visible"), "unit": None, "field": "low_moon.visible"},
        }

        sun_values: dict[str, dict[str, Any]] = {
            "sunrise_time": {"value": _nested(sun_props, "sunrise", "time"), "unit": None, "field": "sunrise.time"},
            "sunrise_azimuth": {"value": _nested(sun_props, "sunrise", "azimuth"), "unit": "°", "field": "sunrise.azimuth"},
            "sunset_time": {"value": _nested(sun_props, "sunset", "time"), "unit": None, "field": "sunset.time"},
            "sunset_azimuth": {"value": _nested(sun_props, "sunset", "azimuth"), "unit": "°", "field": "sunset.azimuth"},
            "solar_noon_time": {"value": _nested(sun_props, "solarnoon", "time"), "unit": None, "field": "solarnoon.time"},
            "solar_noon_elevation": {"value": _nested(sun_props, "solarnoon", "disc_centre_elevation"), "unit": "°", "field": "solarnoon.disc_centre_elevation"},
            "solar_noon_visible": {"value": _nested(sun_props, "solarnoon", "visible"), "unit": None, "field": "solarnoon.visible"},
            "solar_midnight_time": {"value": _nested(sun_props, "solarmidnight", "time"), "unit": None, "field": "solarmidnight.time"},
            "solar_midnight_elevation": {"value": _nested(sun_props, "solarmidnight", "disc_centre_elevation"), "unit": "°", "field": "solarmidnight.disc_centre_elevation"},
            "solar_midnight_visible": {"value": _nested(sun_props, "solarmidnight", "visible"), "unit": None, "field": "solarmidnight.visible"},
        }

        values = {
            item: (moon_values if item in _MOON_IDS else sun_values).get(item, {"value": None})
            for item in requested
        }
        # MET Norway Sunrise 3.0: when.interval describes the calculated
        # mean-solar-day interval, NOT a freshly observed measurement.
        # Transfer exact source strings, then validate/convert them only at
        # the central consumer UTC ingress according to the provider registry.
        def _bounds(raw_payload: dict[str, Any]) -> tuple[Any, Any]:
            when = raw_payload.get("when")
            bounds = when.get("interval") if isinstance(when, dict) else None
            if not isinstance(bounds, list) or len(bounds) != 2:
                return None, None
            return bounds[0], bounds[1]

        moon_bounds, sun_bounds = _bounds(moon_payload), _bounds(sun_payload)
        for capability_id, entry in values.items():
            start, end = moon_bounds if capability_id in _MOON_IDS else sun_bounds
            entry["interval_start"] = start
            entry["interval_end"] = end

        return {
            "provider": self.id,
            "provider_name": self.name,
            "source_class": "astronomy",
            "latitude": latitude,
            "longitude": longitude,
            "data_time": None,  # date-interval boundary is not an observation
            "values": values,
            "attribution": "Meteorologisk institutt / MET Norway",
        }
