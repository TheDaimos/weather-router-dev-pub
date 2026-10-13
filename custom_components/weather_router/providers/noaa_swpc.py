"""NOAA SWPC solar image-sequence provider for WeatherRouter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo

_BASE = "https://services.swpc.noaa.gov"
_OVATION_URL = f"{_BASE}/json/ovation_aurora_latest.json"
_USER_AGENT = "WeatherRouter/0.10 (+https://github.com/TheDaimos/weather-router-dev-pub)"
_FRAME_LIMIT = 72
_TIMESTAMP_RE = re.compile(
    r"_s(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})"
    r"T(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})Z"
)


@dataclass(frozen=True, slots=True)
class _SuviSpec:
    capability_id: str
    name: str
    wavelength: str
    description: str
    strengths: tuple[str, ...]


_SPECS = (
    _SuviSpec(
        "solar_suvi_094",
        "SUVI · 094 Å",
        "094",
        "Sehr heißes Plasma und besonders aktive Flaring-Regionen im extremen Ultraviolett.",
        ("sehr heißes Flare-Plasma", "aktive Regionen", "Vollscheibenbild"),
    ),
    _SuviSpec(
        "solar_suvi_131",
        "SUVI · 131 Å",
        "131",
        "Sehr heißes Flare-Plasma mit zusätzlichem Beitrag kühlerer Strukturen.",
        ("Flare-Plasma", "aktive Regionen", "Vollscheibenbild"),
    ),
    _SuviSpec(
        "solar_suvi_171",
        "SUVI · 171 Å",
        "171",
        "Warme Korona und Übergangsregion; koronale Strukturen sind besonders gut sichtbar.",
        ("Koronastrukturen", "aktive Regionen", "Vollscheibenbild"),
    ),
    _SuviSpec(
        "solar_suvi_195",
        "SUVI · 195 Å",
        "195",
        "Warme Korona für großräumige Struktur, aktive Regionen und koronale Löcher.",
        ("Korona", "koronale Löcher", "aktive Regionen"),
    ),
    _SuviSpec(
        "solar_suvi_284",
        "SUVI · 284 Å",
        "284",
        "Heiße koronale Strukturen und aktive Regionen.",
        ("heiße Korona", "aktive Regionen", "Vollscheibenbild"),
    ),
    _SuviSpec(
        "solar_suvi_304",
        "SUVI · 304 Å",
        "304",
        "Kühlere Chromosphäre; Filamente und Protuberanzen treten besonders deutlich hervor.",
        ("Chromosphäre", "Filamente", "Protuberanzen"),
    ),
)

_SPEC_MAP = {item.capability_id: item for item in _SPECS}
_COVERAGE = "Sonne · Vollscheibe / GOES SUVI"

_CAPABILITIES = tuple(
    CapabilityInfo(
        id=spec.capability_id,
        name=spec.name,
        unit=None,
        source_class="observation",
        render_mode="image_sequence",
        description=spec.description,
        coverage=_COVERAGE,
        temporal_resolution="typisch etwa 4 Minuten",
        typical_latency="nahe Echtzeit, abhängig von SWPC-Aufbereitung",
        strengths=spec.strengths,
        limitations=(
            "kein georeferenzierter Erd-Kartenlayer",
            "Farbgebung ist produktspezifisch und keine natürliche Echtfarbe",
        ),
        documentation_url="https://www.swpc.noaa.gov/products/goes-solar-ultraviolet-imager-suvi",
    )
    for spec in _SPECS
) + (
    CapabilityInfo(
        id="aurora_ovation_latest",
        name="Aurora · OVATION Wahrscheinlichkeitsgitter",
        unit=None,
        source_class="forecast",
        render_mode="data_file",
        description=(
            "Globales erdbezogenes OVATION-Datengitter der modellierten "
            "Aurora-Wahrscheinlichkeit."
        ),
        coverage="Globales Earth-Grid · beide Hemisphären",
        temporal_resolution="laufend aktualisierte kurzfristige Vorhersage",
        typical_latency="nahe Echtzeit, abhängig von SWPC-Aufbereitung",
        strengths=(
            "offizielle NOAA/SWPC-Quelle",
            "maschinenlesbares globales Koordinatengitter",
            "Observation Time und Forecast Time getrennt verfügbar",
        ),
        limitations=(
            "modellierte Vorhersage, keine direkte Aurora-Beobachtung",
            "keine lokale Sichtbarkeitsgarantie",
            "Bewölkung, Dunkelheit und Horizont werden nicht kombiniert",
        ),
        documentation_url="https://www.swpc.noaa.gov/products/aurora-30-minute-forecast",
    ),
)


def _timestamp_from_url(value: str) -> str | None:
    match = _TIMESTAMP_RE.search(value)
    if not match:
        return None
    parts = {key: int(raw) for key, raw in match.groupdict().items()}
    try:
        return datetime(
            parts["year"],
            parts["month"],
            parts["day"],
            parts["hour"],
            parts["minute"],
            parts["second"],
            tzinfo=timezone.utc,
        ).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def _safe_frame_url(raw: Any, wavelength: str) -> str | None:
    if not isinstance(raw, str) or not raw:
        return None
    absolute = urljoin(f"{_BASE}/", raw)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.netloc != "services.swpc.noaa.gov":
        return None
    allowed = (
        f"/images/animations/suvi/primary/{wavelength}/",
        f"/images/animations/suvi/secondary/{wavelength}/",
    )
    if not parsed.path.startswith(allowed):
        return None
    if not parsed.path.lower().endswith(".png"):
        return None
    return absolute


class NoaaSwpcProvider:
    """NOAA Space Weather Prediction Center solar imagery adapter."""

    id = "noaa_swpc"
    name = "NOAA SWPC · Sonne"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Das NOAA Space Weather Prediction Center stellt operationelle "
                "Weltraumwetterdaten bereit. WeatherRouter integriert zunächst die "
                "GOES-SUVI-Vollscheibenbilder der Sonne."
            ),
            coverage="Sonne / Weltraumwetter; keine normale Erd-Wetterabdeckung",
            strengths=(
                "offizielle NOAA/SWPC-Quelle",
                "sechs EUV-Wellenlängen",
                "laufende Vollscheiben-Bildserien",
                "kein API-Schlüssel erforderlich",
            ),
            limitations=(
                "Sonnenbilder sind keine Erd-Rasterkacheln",
                "Primär-/Sekundärsatellit kann von NOAA gewechselt werden",
                "kurze Datenlücken während Umschaltungen sind möglich",
            ),
            documentation_url="https://www.swpc.noaa.gov/products/goes-solar-ultraviolet-imager-suvi",
            attribution="NOAA Space Weather Prediction Center · GOES SUVI",
            services=(
                {
                    "name": "GOES Solar Ultraviolet Imager (SUVI)",
                    "status": "integriert",
                    "note": "094, 131, 171, 195, 284 und 304 Å als generische Bildfolgen",
                },
                {
                    "name": "Aurora OVATION",
                    "status": "integriert",
                    "note": "globales maschinenlesbares Wahrscheinlichkeitsgitter als Consumer-Datendatei",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="solar_image_sequence",
                scheme="https",
                host="services.swpc.noaa.gov",
                port=443,
                target_type="api_and_image",
                required=True,
                capabilities=tuple(spec.capability_id for spec in _SPECS),
                note=(
                    "Maschinenlesbare SUVI-Animationslisten plus zugehörige PNG-Bilder. "
                    "Abrufe erfolgen nur bei expliziter Nutzung des Sonnenviewers."
                ),
            ),
            NetworkTargetInfo(
                purpose="aurora_probability_grid",
                scheme="https",
                host="services.swpc.noaa.gov",
                port=443,
                target_type="data_file",
                required=True,
                capabilities=("aurora_ovation_latest",),
                note=(
                    "NOAA/SWPC OVATION Aurora Latest JSON; globales Earth-Grid "
                    "mit Observation Time, Forecast Time und Koordinatentripeln."
                ),
            ),
        )

    async def async_get_data_file(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Resolve and validate the current NOAA OVATION Aurora JSON grid."""
        if capability_id != "aurora_ovation_latest":
            raise ValueError(f"Unsupported NOAA SWPC data-file capability: {capability_id}")

        session = async_get_clientsession(hass)
        async with session.get(
            _OVATION_URL,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
            },
            timeout=20,
        ) as response:
            response.raise_for_status()
            payload = await response.json()

        if not isinstance(payload, dict):
            raise ValueError("NOAA SWPC OVATION response is not a JSON object")

        observation_time = payload.get("Observation Time")
        forecast_time = payload.get("Forecast Time")
        data_format = payload.get("Data Format")
        coordinates = payload.get("coordinates")

        if not isinstance(observation_time, str) or not observation_time:
            raise ValueError("NOAA SWPC OVATION response has no Observation Time")
        if not isinstance(forecast_time, str) or not forecast_time:
            raise ValueError("NOAA SWPC OVATION response has no Forecast Time")
        if not isinstance(data_format, str) or "Longitude" not in data_format or "Latitude" not in data_format:
            raise ValueError("NOAA SWPC OVATION response has an unsupported Data Format")
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError("NOAA SWPC OVATION response contains no coordinates")

        sample = coordinates[0]
        if (
            not isinstance(sample, list)
            or len(sample) < 3
            or not all(isinstance(value, (int, float)) for value in sample[:3])
        ):
            raise ValueError("NOAA SWPC OVATION coordinate rows are malformed")

        return {
            "provider": self.id,
            "provider_name": self.name,
            "capability": capability_id,
            "capability_name": "Aurora · OVATION Wahrscheinlichkeitsgitter",
            "source_class": "forecast",
            "render_mode": "data_file",
            "format": "json",
            "content_type": "application/json",
            "transport": "direct",
            "url": _OVATION_URL,
            "data_time": observation_time,
            "valid_time": forecast_time,
            "attribution": "NOAA Space Weather Prediction Center · OVATION Aurora",
            "metadata_url": "https://www.swpc.noaa.gov/products/aurora-30-minute-forecast",
            "coverage": "Globales Earth-Grid · beide Hemisphären",
            "provider_metadata": {
                "model": "OVATION",
                "data_format": data_format,
                "coordinate_count": len(coordinates),
                "observation_time": observation_time,
                "forecast_time": forecast_time,
                "field_semantics": "[longitude, latitude, aurora_probability_percent]",
                "local_visibility_guarantee": False,
            },
        }

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        spec = _SPEC_MAP.get(capability_id)
        if spec is None:
            raise ValueError(f"Unsupported NOAA SWPC capability: {capability_id}")

        session = async_get_clientsession(hass)
        source_kind = "primary"
        payload: Any = None
        last_error: Exception | None = None

        for kind in ("primary", "secondary"):
            url = (
                f"{_BASE}/products/animations/"
                f"suvi-{kind}-{spec.wavelength}.json"
            )
            try:
                async with session.get(
                    url,
                    headers={
                        "User-Agent": _USER_AGENT,
                        "Accept": "application/json",
                    },
                    timeout=20,
                ) as response:
                    response.raise_for_status()
                    candidate = await response.json()
                if isinstance(candidate, list) and candidate:
                    payload = candidate
                    source_kind = kind
                    break
            except Exception as err:  # noqa: BLE001 - controlled primary/secondary fallback
                last_error = err

        if not isinstance(payload, list) or not payload:
            if last_error is not None:
                raise last_error
            raise ValueError("NOAA SWPC returned no SUVI animation frames")

        frames: list[dict[str, Any]] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            frame_url = _safe_frame_url(raw.get("url"), spec.wavelength)
            if frame_url is None:
                continue
            frame_time = _timestamp_from_url(frame_url)
            if frame_time is None:
                continue
            frames.append(
                {
                    "time": frame_time,
                    "kind": "observation",
                    "image_url": frame_url,
                }
            )

        frames.sort(key=lambda item: item["time"])
        if len(frames) > _FRAME_LIMIT:
            frames = frames[-_FRAME_LIMIT:]
        if not frames:
            raise ValueError("NOAA SWPC SUVI frame list contained no safe usable images")

        latest_index = len(frames) - 1
        return {
            "provider": self.id,
            "provider_name": self.name,
            "capability": capability_id,
            "capability_name": spec.name,
            "source_class": "observation",
            "render_mode": "image_sequence",
            "frame_time": frames[latest_index]["time"],
            "attribution": "NOAA Space Weather Prediction Center · GOES SUVI",
            "network_hosts": ["services.swpc.noaa.gov"],
            "provider_metadata": {
                "wavelength_angstrom": spec.wavelength,
                "satellite_role": source_kind,
                "coverage": _COVERAGE,
                "cadence": "typisch etwa 4 Minuten",
            },
            "timeline": {
                "mode": "datetime",
                "default": frames[latest_index]["time"],
                "default_index": latest_index,
                "current_index": latest_index,
                "frames": frames,
            },
            "media": {
                "kind": "solar_full_disk",
                "fit": "contain",
                "background": "#000000",
            },
        }
