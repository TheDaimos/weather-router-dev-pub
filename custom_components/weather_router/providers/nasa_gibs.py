"""NASA GIBS multi-service observed-satellite provider for WeatherRouter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant

from ..spatial_coverage import wms_layer_geographic_coverage
from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .wms_satellite import (
    async_capabilities,
    iso_wms,
    layer_style_metadata,
    layer_time_dimension,
    named_layer_names,
    tile_url,
    trim_observation_times,
)

_WMS = "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi"
_DOC_BASE = "https://gibs.earthdata.nasa.gov/layer-metadata/v1.0/"


@dataclass(frozen=True, slots=True)
class _LayerSpec:
    capability_id: str
    name: str
    layer: str
    coverage: str
    temporal_resolution: str
    description: str
    strengths: tuple[str, ...]
    limitations: tuple[str, ...]
    max_frames: int
    max_zoom: int
    default_opacity: float
    time_mode: str = "datetime"
    stable_completed_day: bool = False
    documentation_file: str | None = None


_SPECS = (
    _LayerSpec(
        "satellite_imagery_true_color",
        "MODIS Terra · True Color",
        "MODIS_Terra_CorrectedReflectance_TrueColor",
        "Global",
        "täglich",
        "Hochauflösendes korrigiertes Echtfarben-Tagesbild von MODIS Terra.",
        ("globale Abdeckung", "hoher visueller Detailgrad", "lange Zeitreihe"),
        ("nur ein Daten-Tag pro Tag", "laufender Tag kann regional noch unvollständig sein"),
        14,
        9,
        0.88,
        "date",
        True,
        "MODIS_Terra_CorrectedReflectance_TrueColor.json",
    ),
    _LayerSpec(
        "satellite_goes_east_geocolor",
        "GOES-East · GeoColor",
        "GOES-East_ABI_GeoColor",
        "Amerika / westlicher Atlantik",
        "untertägig, typischerweise 10 Minuten",
        "GeoColor kombiniert tagsüber annähernde Echtfarbe und nachts multispektrales Infrarot.",
        ("sehr hohe zeitliche Auflösung", "Tag und Nacht", "Wolkenentwicklung gut sichtbar"),
        ("regionaler geostationärer Sichtbereich", "für Mitteleuropa nicht der primäre Satellit"),
        36,
        7,
        0.9,
        documentation_file="GOES-East_ABI_GeoColor.json",
    ),
    _LayerSpec(
        "satellite_goes_west_geocolor",
        "GOES-West · GeoColor",
        "GOES-West_ABI_GeoColor",
        "Amerika / östlicher und zentraler Pazifik",
        "untertägig, typischerweise 10 Minuten",
        "GeoColor von GOES-West für den westlichen geostationären Sichtbereich.",
        ("sehr hohe zeitliche Auflösung", "Tag und Nacht", "Pazifik und westliches Amerika"),
        ("regionaler geostationärer Sichtbereich", "nicht für Europa optimiert"),
        36,
        7,
        0.9,
        documentation_file="GOES-West_ABI_GeoColor.json",
    ),
    _LayerSpec(
        "satellite_goes_east_clean_ir",
        "GOES-East · Clean Infrared",
        "GOES-East_ABI_Band13_Clean_Infrared",
        "Amerika / westlicher Atlantik",
        "10 Minuten",
        "Infrarotkanal 13 zur Darstellung von Wolkenstrukturen und Wolkenoberseitentemperaturen.",
        ("Tag und Nacht", "Wolkenentwicklung", "hohe zeitliche Auflösung"),
        ("regionaler GOES-East-Sichtbereich", "kein natürliches Farbbild"),
        36,
        7,
        0.86,
        documentation_file="GOES-East_ABI_Band13_Clean_Infrared.json",
    ),
    _LayerSpec(
        "satellite_goes_west_clean_ir",
        "GOES-West · Clean Infrared",
        "GOES-West_ABI_Band13_Clean_Infrared",
        "Amerika / Pazifik",
        "10 Minuten",
        "Infrarotkanal 13 von GOES-West für Wolkenstrukturen bei Tag und Nacht.",
        ("Tag und Nacht", "Wolkenentwicklung", "hohe zeitliche Auflösung"),
        ("regionaler GOES-West-Sichtbereich", "kein natürliches Farbbild"),
        36,
        7,
        0.86,
        documentation_file="GOES-West_ABI_Band13_Clean_Infrared.json",
    ),
    _LayerSpec(
        "satellite_goes_east_visible_red",
        "GOES-East · Red Visible",
        "GOES-East_ABI_Band2_Red_Visible_1km",
        "Amerika / westlicher Atlantik",
        "10 Minuten",
        "Hochauflösender sichtbarer Rotkanal für Wolken- und Oberflächenstrukturen bei Tageslicht.",
        ("1-km-Sichtkanal", "feine Wolkenstrukturen", "hohe zeitliche Auflösung"),
        ("nur bei ausreichendem Tageslicht sinnvoll", "regionaler Sichtbereich"),
        36,
        8,
        0.86,
        documentation_file="GOES-East_ABI_Band2_Red_Visible_1km.json",
    ),
    _LayerSpec(
        "satellite_goes_west_visible_red",
        "GOES-West · Red Visible",
        "GOES-West_ABI_Band2_Red_Visible_1km",
        "Amerika / Pazifik",
        "10 Minuten",
        "Hochauflösender sichtbarer Rotkanal von GOES-West.",
        ("1-km-Sichtkanal", "feine Wolkenstrukturen", "hohe zeitliche Auflösung"),
        ("nur bei Tageslicht sinnvoll", "regionaler Sichtbereich"),
        36,
        8,
        0.86,
        documentation_file="GOES-West_ABI_Band2_Red_Visible_1km.json",
    ),
    _LayerSpec(
        "satellite_goes_east_air_mass",
        "GOES-East · Air Mass",
        "GOES-East_ABI_Air_Mass",
        "Amerika / westlicher Atlantik",
        "10 Minuten",
        "Mehrkanal-Komposit zur Unterscheidung von Luftmassen und großräumigen dynamischen Strukturen.",
        ("Tag und Nacht", "Luftmassenanalyse", "hohe zeitliche Auflösung"),
        ("meteorologisches Falschfarbenprodukt", "regionaler Sichtbereich"),
        36,
        7,
        0.86,
        documentation_file="GOES-East_ABI_Air_Mass.json",
    ),
    _LayerSpec(
        "satellite_goes_west_air_mass",
        "GOES-West · Air Mass",
        "GOES-West_ABI_Air_Mass",
        "Amerika / Pazifik",
        "10 Minuten",
        "Mehrkanal-Komposit für Luftmassen und großräumige dynamische Strukturen.",
        ("Tag und Nacht", "Luftmassenanalyse", "hohe zeitliche Auflösung"),
        ("meteorologisches Falschfarbenprodukt", "regionaler Sichtbereich"),
        36,
        7,
        0.86,
        documentation_file="GOES-West_ABI_Air_Mass.json",
    ),
    _LayerSpec(
        "satellite_goes_east_dust",
        "GOES-East · Dust",
        "GOES-East_ABI_Dust",
        "Amerika / Atlantik",
        "10 Minuten",
        "Falschfarbenkomposit zur Hervorhebung von Staub und ausgewählten Wolkeneigenschaften.",
        ("Tag und Nacht", "Stauberkennung", "hohe zeitliche Auflösung"),
        ("Interpretation ist produktspezifisch", "regionaler Sichtbereich"),
        36,
        7,
        0.82,
        documentation_file="GOES-East_ABI_Dust.json",
    ),
    _LayerSpec(
        "satellite_goes_west_dust",
        "GOES-West · Dust",
        "GOES-West_ABI_Dust",
        "Amerika / Pazifik",
        "10 Minuten",
        "Falschfarbenkomposit zur Staub- und Wolkenanalyse.",
        ("Tag und Nacht", "Stauberkennung", "hohe zeitliche Auflösung"),
        ("Interpretation ist produktspezifisch", "regionaler Sichtbereich"),
        36,
        7,
        0.82,
        documentation_file="GOES-West_ABI_Dust.json",
    ),
    _LayerSpec(
        "satellite_goes_east_fire_temperature",
        "GOES-East · Fire Temperature",
        "GOES-East_ABI_FireTemp",
        "Amerika / westlicher Atlantik",
        "10 Minuten",
        "Falschfarbenprodukt zur Hervorhebung thermischer Brand-/Hitze-Signaturen.",
        ("schnelle thermische Beobachtung", "Tag und Nacht"),
        ("keine eigenständige Brandbestätigung", "regionaler Sichtbereich"),
        36,
        7,
        0.88,
        documentation_file="GOES-East_ABI_FireTemp.json",
    ),
    _LayerSpec(
        "satellite_goes_west_fire_temperature",
        "GOES-West · Fire Temperature",
        "GOES-West_ABI_FireTemp",
        "Amerika / Pazifik",
        "10 Minuten",
        "Falschfarbenprodukt zur Hervorhebung thermischer Brand-/Hitze-Signaturen.",
        ("schnelle thermische Beobachtung", "Tag und Nacht"),
        ("keine eigenständige Brandbestätigung", "regionaler Sichtbereich"),
        36,
        7,
        0.88,
        documentation_file="GOES-West_ABI_FireTemp.json",
    ),
    _LayerSpec(
        "satellite_himawari_air_mass",
        "Himawari-9 · Air Mass",
        "Himawari_AHI_Air_Mass",
        "Asien / Australien / westlicher Pazifik",
        "10 Minuten",
        "AHI-Luftmassenkomposit für den Himawari-9-Sichtbereich.",
        ("Tag und Nacht", "10-Minuten-Folge", "großer asiatisch-pazifischer Sichtbereich"),
        ("meteorologisches Falschfarbenprodukt", "nicht für Europa optimiert"),
        36,
        7,
        0.86,
        documentation_file="Himawari_AHI_Air_Mass.json",
    ),
    _LayerSpec(
        "satellite_himawari_clean_ir",
        "Himawari-9 · Clean Infrared",
        "Himawari_AHI_Band13_Clean_Infrared",
        "Asien / Australien / westlicher Pazifik",
        "10 Minuten",
        "AHI-Infrarotkanal 13 für Wolkenstrukturen bei Tag und Nacht.",
        ("Tag und Nacht", "10-Minuten-Folge", "Wolkenoberseiten gut erkennbar"),
        ("kein natürliches Farbbild", "regionaler Sichtbereich"),
        36,
        7,
        0.86,
        documentation_file="Himawari_AHI_Band13_Clean_Infrared.json",
    ),
    _LayerSpec(
        "satellite_himawari_visible_red",
        "Himawari-9 · Red Visible",
        "Himawari_AHI_Band3_Red_Visible_1km",
        "Asien / Australien / westlicher Pazifik",
        "10 Minuten",
        "Hochauflösender sichtbarer AHI-Kanal für Wolkenstrukturen bei Tageslicht.",
        ("1-km-Sichtkanal", "10-Minuten-Folge", "feine Wolkenstrukturen"),
        ("nur bei Tageslicht sinnvoll", "regionaler Sichtbereich"),
        36,
        8,
        0.86,
        documentation_file="Himawari_AHI_Band3_Red_Visible_1km.json",
    ),
    _LayerSpec(
        "satellite_precipitation_imerg_30min",
        "IMERG · Niederschlagsrate 30 min",
        "IMERG_Precipitation_Rate_30min",
        "Nahezu global",
        "30 Minuten",
        "Multisatelliten-Niederschlagsrate aus GPM IMERG in halbstündlicher Auflösung.",
        ("nahezu globale Niederschlagsbeobachtung", "30-Minuten-Zeitachse", "ergänzt Radar außerhalb lokaler Netze"),
        ("Satellitenschätzung statt Bodenradar", "Latenz und Qualität hängen vom verfügbaren IMERG-Run ab"),
        24,
        7,
        0.72,
        documentation_file="IMERG_Precipitation_Rate_30min.json",
    ),
)

_SPEC_MAP = {spec.capability_id: spec for spec in _SPECS}


def _doc_url(spec: _LayerSpec) -> str | None:
    return f"{_DOC_BASE}{spec.documentation_file}" if spec.documentation_file else None


def _times_for_spec(
    spec: _LayerSpec,
    raw_times: list[datetime],
    now: datetime,
) -> list[datetime]:
    """Return the stable, bounded timeline for one NASA layer."""
    if spec.stable_completed_day:
        today_utc = now.astimezone(timezone.utc).date()
        completed = [
            value
            for value in raw_times
            if value.astimezone(timezone.utc).date() < today_utc
        ]
        return trim_observation_times(completed or raw_times, spec.max_frames)
    return trim_observation_times(raw_times, spec.max_frames)


_CAPABILITIES = tuple(
    CapabilityInfo(
        spec.capability_id,
        f"NASA GIBS · {spec.name}",
        "mm/h" if spec.capability_id == "satellite_precipitation_imerg_30min" else None,
        "observation",
        "raster_tile",
        spec.description,
        spec.coverage,
        spec.temporal_resolution,
        None,
        spec.strengths,
        spec.limitations,
        _doc_url(spec),
    )
    for spec in _SPECS
)


class NasaGibsProvider:
    """NASA Global Imagery Browse Services WMS adapter."""

    id = "nasa_gibs"
    name = "NASA GIBS"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        """Return the WeatherRouter-selected GIBS imagery capabilities."""
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        """Return explanatory provider metadata for the generic info popup."""
        return ProviderInfo(
            summary=(
                "NASA EOSDIS Global Imagery Browse Services (GIBS) stellt "
                "beobachtungsbasierte Satelliten- und Niederschlagsprodukte als "
                "kartenfähige Dienste bereit."
            ),
            coverage="Global plus regionale geostationäre Sichtbereiche",
            strengths=(
                "große Auswahl schlüsselloser Erdbeobachtungsprodukte",
                "einheitlicher WMS-/WMTS-Dienst",
                "hochfrequente GOES-/Himawari-Produkte und globale Tagesprodukte",
            ),
            limitations=(
                "geostationäre GOES-/Himawari-Produkte sind regional begrenzt",
                "MODIS True Color ist ein Tagesprodukt",
                "IMERG ist eine satellitenbasierte Niederschlagsschätzung und kein Bodenradar",
            ),
            documentation_url="https://www.earthdata.nasa.gov/data/tools/gibs",
            attribution="NASA EOSDIS GIBS",
            services=(
                {"name": "MODIS Terra", "status": "integriert", "note": "global · täglich"},
                {"name": "GOES-East / GOES-West ABI", "status": "integriert", "note": "regional · hochfrequent"},
                {"name": "Himawari-9 AHI", "status": "integriert", "note": "Asien/Pazifik · 10 Minuten"},
                {"name": "GPM IMERG", "status": "integriert", "note": "Niederschlagsrate · 30 Minuten"},
            ),
        )

    async def async_get_coverage(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Return machine-readable geographic coverage from NASA GIBS WMS metadata."""
        spec = _SPEC_MAP.get(capability_id)
        if spec is None:
            raise ValueError(f"Unsupported NASA GIBS coverage capability: {capability_id}")
        root = await async_capabilities(hass, _WMS)
        coverage = wms_layer_geographic_coverage(root, spec.layer)
        if coverage is None:
            raise ValueError(
                f"NASA GIBS WMS has no machine-readable geographic coverage: {spec.layer}"
            )
        result = dict(coverage)
        result["coverage_metadata_scope"] = "layer_specific_wms"
        result["provider_metadata_source"] = "NASA GIBS WMS GetCapabilities"
        return result

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        """Return the public GIBS map-service destination."""
        return (
            NetworkTargetInfo(
                purpose="observed_satellite_wms",
                scheme="https",
                host="gibs.earthdata.nasa.gov",
                port=443,
                target_type="wms",
                required=True,
                capabilities=tuple(spec.capability_id for spec in _SPECS),
                note=(
                    "Öffentlicher NASA-GIBS-WMS in EPSG:3857 für MODIS, "
                    "GOES-East/West, Himawari und IMERG."
                ),
            ),
        )

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        """Return secret-free GIBS layer/timeline snapshots."""
        if capability_id is not None and capability_id not in _SPEC_MAP:
            return {
                "ok": False,
                "stage": "capability_selection",
                "error": {
                    "type": "ValueError",
                    "message": f"Unsupported NASA GIBS capability: {capability_id}",
                },
            }

        selected_specs = (
            (_SPEC_MAP[capability_id],)
            if capability_id is not None
            else _SPECS
        )
        attempts: list[dict[str, Any]] = []
        try:
            root = await async_capabilities(hass, _WMS, attempts=attempts)
            names = set(named_layer_names(root))
            now = datetime.now(timezone.utc)
            layers: list[dict[str, Any]] = []
            missing: list[str] = []

            for spec in selected_specs:
                present = spec.layer in names
                raw_times: list[datetime] = []
                declared_default: str | None = None
                raw_dimension: str | None = None
                styles: dict[str, Any] = {}
                if present:
                    raw_times, declared_default, raw_dimension = layer_time_dimension(
                        root,
                        spec.layer,
                        now,
                    )
                    styles = layer_style_metadata(root, spec.layer)
                else:
                    missing.append(spec.capability_id)

                times = _times_for_spec(spec, raw_times, now)
                layers.append(
                    {
                        "capability": spec.capability_id,
                        "expected_layer": spec.layer,
                        "present": present,
                        "coverage": spec.coverage,
                        "temporal_resolution": spec.temporal_resolution,
                        "source_class": "observation",
                        "time_dimension": {
                            "raw_count": len(raw_times),
                            "trimmed_count": len(times),
                            "first": iso_wms(raw_times[0]) if raw_times else None,
                            "last": iso_wms(raw_times[-1]) if raw_times else None,
                            "selected_first": iso_wms(times[0]) if times else None,
                            "selected_last": iso_wms(times[-1]) if times else None,
                            "declared_default": declared_default,
                            "raw": raw_dimension,
                            "stable_completed_day": spec.stable_completed_day,
                        },
                        "style_metadata": styles,
                    }
                )
        except Exception as err:  # noqa: BLE001 - explicit diagnostics capture
            return {
                "ok": False,
                "stage": "get_capabilities",
                "attempts": attempts,
                "error": {
                    "type": type(err).__name__,
                    "message": str(err),
                },
            }

        return {
            "ok": not missing,
            "stage": "layer_discovery",
            "attempts": attempts,
            "service": {
                "wms_version": root.attrib.get("version"),
                "named_layer_count": len(names),
                "projection": "EPSG:3857",
            },
            "layers": layers,
            "missing_capabilities": missing,
        }

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Return one GIBS layer through the generic raster/timeline path."""
        spec = _SPEC_MAP.get(capability_id)
        if spec is None:
            raise ValueError(f"Unsupported NASA GIBS capability: {capability_id}")

        root = await async_capabilities(hass, _WMS)
        now = datetime.now(timezone.utc)
        raw_times, declared_default, _raw = layer_time_dimension(root, spec.layer, now)
        times = _times_for_spec(spec, raw_times, now)
        styles = layer_style_metadata(root, spec.layer)
        style_name = styles.get("default_style")

        frames = [
            {
                "time": int(value.timestamp()),
                "tile_url": tile_url(
                    _WMS,
                    spec.layer,
                    value,
                    time_mode=spec.time_mode,
                    style_name=style_name,
                ),
                "kind": (
                    "estimate"
                    if spec.capability_id == "satellite_precipitation_imerg_30min"
                    else "observation"
                ),
            }
            for value in times
        ]

        selected = frames[-1] if frames else None
        selected_time = times[-1] if times else None
        current_tile_url = (
            selected["tile_url"]
            if selected is not None
            else tile_url(
                _WMS,
                spec.layer,
                None,
                time_mode=spec.time_mode,
                style_name=style_name,
            )
        )

        host = urlsplit(_WMS).hostname
        descriptor: dict[str, Any] = {
            "provider": self.id,
            "provider_name": self.name,
            "capability": capability_id,
            "source_class": "observation",
            "render_mode": "raster_tile",
            "frame_time": selected["time"] if selected else None,
            "tile_url": current_tile_url,
            "tile_size": 256,
            "max_zoom": spec.max_zoom,
            "default_opacity": spec.default_opacity,
            "attribution": (
                'Imagery: <a href="https://www.earthdata.nasa.gov/data/tools/gibs" '
                'target="_blank" rel="noopener noreferrer">NASA EOSDIS GIBS</a>'
            ),
            "network_hosts": [host] if host else [],
            "provider_metadata": {
                "service": "WMS",
                "layer": spec.layer,
                "projection": "EPSG:3857",
                "coverage": spec.coverage,
                "temporal_resolution": spec.temporal_resolution,
                "time_granularity": "day" if spec.time_mode == "date" else "datetime",
                "latest_policy": "completed_day" if spec.stable_completed_day else "latest_available",
                "current_day_policy": (
                    "exclude_incomplete_daily_composite"
                    if spec.stable_completed_day
                    else None
                ),
                "capabilities_default": declared_default,
                "default_style": style_name,
                "styles": styles.get("styles", []),
                "latest_available": iso_wms(selected_time) if selected_time else None,
            },
        }

        # Preserve a truthful source/phenomenon title even when this WMS
        # publishes no GetLegendGraphic URL. This is NOT a fabricated
        # precipitation colour scale or an assertion of numeric interchange.
        legend_url = styles.get("legend_url")
        descriptor["legend"] = {
            "title": f"NASA GIBS · {spec.name}",
            "style": style_name,
        }
        if isinstance(legend_url, str) and legend_url:
            descriptor["legend"]["url"] = legend_url

        if frames:
            descriptor["timeline"] = {
                "mode": "frames",
                "default": "latest",
                "default_index": len(frames) - 1,
                "current_index": len(frames) - 1,
                "loop": True,
                "frames": frames,
            }

        return descriptor
