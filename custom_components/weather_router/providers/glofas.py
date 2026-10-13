"""Copernicus GloFAS global flood forecast layers for WeatherRouter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from homeassistant.core import HomeAssistant

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

_WMS = "https://ows.globalfloods.eu/glofas-ows/ows.py"
_MAX_FRAMES = 32


@dataclass(frozen=True, slots=True)
class _Layer:
    capability_id: str
    name: str
    layer: str
    source_class: str
    default_opacity: float
    max_zoom: int
    description: str


_LAYERS = (
    _Layer(
        "flood_reporting_points",
        "GloFAS · Hochwasser-Meldepunkte",
        "reportingPoints",
        "forecast",
        0.92,
        10,
        "Globale Meldepunkte mit prognostizierter Überschreitung von 2-, 5- oder 20-jährigen Hochwasserschwellen.",
    ),
    _Layer(
        "flood_probability_5y",
        "GloFAS · Hochwasserwahrscheinlichkeit > 5 Jahre",
        "sumALHEGE",
        "forecast",
        0.82,
        9,
        "Wahrscheinlichkeit, dass der Abfluss innerhalb des Vorhersagehorizonts die 5-jährige Hochwasserschwelle überschreitet.",
    ),
    _Layer(
        "flood_probability_20y",
        "GloFAS · Hochwasserwahrscheinlichkeit > 20 Jahre",
        "sumALEEGE",
        "forecast",
        0.82,
        9,
        "Wahrscheinlichkeit, dass der Abfluss innerhalb des Vorhersagehorizonts die 20-jährige Hochwasserschwelle überschreitet.",
    ),
    _Layer(
        "flood_summary_1_3d",
        "GloFAS · Hochwasser 1–3 Tage",
        "sumAL41EGE",
        "forecast",
        0.84,
        9,
        "Zusammenfassung der Hochwassersignale für die kommenden 1 bis 3 Tage.",
    ),
    _Layer(
        "flood_summary_4_10d",
        "GloFAS · Hochwasser 4–10 Tage",
        "sumAL42EGE",
        "forecast",
        0.84,
        9,
        "Zusammenfassung der Hochwassersignale für die kommenden 4 bis 10 Tage.",
    ),
    _Layer(
        "flood_summary_11_30d",
        "GloFAS · Hochwasser 11–30 Tage",
        "sumAL43EGE",
        "forecast",
        0.80,
        9,
        "Zusammenfassung längerfristiger Hochwassersignale für 11 bis 30 Tage.",
    ),
    _Layer(
        "rapid_flood_mapping",
        "GloFAS · schnelle Überflutungskarte",
        "RapidFloodMapping",
        "forecast",
        0.78,
        11,
        "Prognostizierte Überflutungsfläche für größere Einzugsgebiete auf Basis des GloFAS-Abflusssignals.",
    ),
    _Layer(
        "rapid_impact_assessment",
        "GloFAS · schnelle Folgenabschätzung",
        "RapidImpactAssessment",
        "forecast",
        0.80,
        10,
        "Potenzielle Hochwasserfolgen für Bevölkerung und Landnutzung als modellbasierte globale Einschätzung.",
    ),
    _Layer(
        "flood_hazard_100y",
        "GloFAS · Hochwassergefahr 100 Jahre",
        "FloodHazard100y",
        "climatology",
        0.62,
        10,
        "Statische modellierte Überflutungsgebiete für ein 100-jähriges Hochwasserereignis.",
    ),
)

_LAYER_BY_CAPABILITY = {item.capability_id: item for item in _LAYERS}
_CAPABILITIES = tuple(
    CapabilityInfo(
        item.capability_id,
        item.name,
        None,
        item.source_class,
        "raster_tile",
        description=item.description,
        coverage="Global",
        temporal_resolution="täglich" if item.source_class == "forecast" else "statisch",
        strengths=(
            "globale hydrologische Abdeckung",
            "Copernicus Emergency Management Service / GloFAS",
        ),
        limitations=(
            "modellbasierte Frühwarninformation, keine lokale amtliche Warnung",
            "kleine Einzugsgebiete und lokale Schutzbauwerke können unzureichend abgebildet sein",
        ),
        documentation_url="https://global-flood.emergency.copernicus.eu/",
    )
    for item in _LAYERS
)


class GlofasProvider:
    """Expose open Copernicus GloFAS flood layers through WMS."""

    id = "glofas"
    name = "Copernicus GloFAS"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Copernicus GloFAS liefert globale modellbasierte Hochwasserfrühwarnung, "
                "Schwellenüberschreitungen, Überflutungskarten und Folgenabschätzungen."
            ),
            coverage="Global",
            strengths=(
                "globale Hochwasserfrühwarnung",
                "2-/5-/20-jährige Schwellen und mehrere Vorhersagehorizonte",
                "Rapid Flood Mapping und Folgenabschätzung",
                "öffentlicher GloFAS-WMS ohne Zugangsdaten",
            ),
            limitations=(
                "keine lokale amtliche Warnbehörde",
                "Modellauflösung begrenzt lokale Sturzfluten und sehr kleine Einzugsgebiete",
                "Rapid Flood Mapping berücksichtigt lokale Hochwasserschutzanlagen nicht vollständig",
            ),
            documentation_url="https://global-flood.emergency.copernicus.eu/",
            attribution="Copernicus Emergency Management Service · GloFAS",
            services=tuple(
                {"name": item.name, "status": "integriert", "note": item.description}
                for item in _LAYERS
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="global_flood_forecast_wms",
                scheme="https",
                host="ows.globalfloods.eu",
                port=443,
                target_type="wms",
                required=True,
                capabilities=tuple(item.capability_id for item in _LAYERS),
                note="Offener Copernicus-GloFAS-WMS für globale Hochwasserprodukte.",
            ),
        )

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        requested = (
            [_LAYER_BY_CAPABILITY[capability_id]]
            if capability_id in _LAYER_BY_CAPABILITY
            else list(_LAYERS) if capability_id is None else []
        )
        if not requested:
            return {
                "ok": False,
                "stage": "capability_selection",
                "error": {
                    "type": "ValueError",
                    "message": f"Unsupported GloFAS capability: {capability_id}",
                },
            }

        attempts: list[dict[str, Any]] = []
        try:
            root = await async_capabilities(hass, _WMS, attempts=attempts)
            names = set(named_layer_names(root))
        except Exception as err:  # noqa: BLE001
            return {
                "ok": False,
                "stage": "get_capabilities",
                "attempts": attempts,
                "error": {"type": type(err).__name__, "message": str(err)},
            }

        rows = []
        missing = []
        now = datetime.now(timezone.utc)
        for item in requested:
            present = item.layer in names
            raw_times: list[datetime] = []
            declared_default = None
            styles: dict[str, Any] = {}
            if present:
                raw_times, declared_default, _raw = layer_time_dimension(
                    root, item.layer, now
                )
                styles = layer_style_metadata(root, item.layer)
            else:
                missing.append(item.capability_id)
            rows.append(
                {
                    "capability": item.capability_id,
                    "layer": item.layer,
                    "present": present,
                    "source_class": item.source_class,
                    "time_count": len(raw_times),
                    "latest": iso_wms(raw_times[-1]) if raw_times else None,
                    "declared_default": declared_default,
                    "style_metadata": styles,
                }
            )

        return {
            "ok": not missing,
            "stage": "layer_discovery",
            "attempts": attempts,
            "service": {
                "endpoint": _WMS,
                "wms_version": root.attrib.get("version"),
                "named_layer_count": len(names),
            },
            "layers": rows,
            "missing_capabilities": missing,
        }

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        item = _LAYER_BY_CAPABILITY.get(capability_id)
        if item is None:
            raise ValueError(f"Unsupported GloFAS capability: {capability_id}")

        root = await async_capabilities(hass, _WMS)
        if item.layer not in set(named_layer_names(root)):
            raise ValueError(f"GloFAS WMS layer not available: {item.layer}")

        now = datetime.now(timezone.utc)
        times, declared_default, _raw = layer_time_dimension(root, item.layer, now)
        times = trim_observation_times(times, _MAX_FRAMES)
        styles = layer_style_metadata(root, item.layer)
        style_name = styles.get("default_style")
        selected_time = times[-1] if times else None

        frames = [
            {
                "time": int(value.timestamp()),
                "tile_url": tile_url(
                    _WMS,
                    item.layer,
                    value,
                    time_mode="datetime",
                    style_name=style_name,
                ),
                "kind": "forecast",
            }
            for value in times
        ]
        current_url = (
            frames[-1]["tile_url"]
            if frames
            else tile_url(
                _WMS,
                item.layer,
                None,
                time_mode="datetime",
                style_name=style_name,
            )
        )
        host = urlsplit(_WMS).hostname
        descriptor: dict[str, Any] = {
            "provider": self.id,
            "provider_name": self.name,
            "capability": capability_id,
            "source_class": item.source_class,
            "render_mode": "raster_tile",
            "frame_time": frames[-1]["time"] if frames else None,
            "tile_url": current_url,
            "tile_size": 256,
            "max_zoom": item.max_zoom,
            "default_opacity": item.default_opacity,
            "attribution": (
                'Flood information: <a href="https://global-flood.emergency.copernicus.eu/" '
                'target="_blank" rel="noopener noreferrer">Copernicus GloFAS</a>'
            ),
            "network_hosts": [host] if host else [],
            "provider_metadata": {
                "service": "WMS",
                "layer": item.layer,
                "projection": "EPSG:3857",
                "capabilities_default": declared_default,
                "default_style": style_name,
                "styles": styles.get("styles", []),
                "latest_available": iso_wms(selected_time) if selected_time else None,
                "model_warning": "GloFAS ist eine modellbasierte Frühwarnquelle und keine lokale amtliche Warnung.",
            },
        }

        legend_url = styles.get("legend_url")
        if legend_url:
            descriptor["legend"] = {
                "title": item.name,
                "url": legend_url,
                "style": style_name,
            }

        if frames:
            descriptor["timeline"] = {
                "mode": "frames",
                "default": "latest",
                "default_index": len(frames) - 1,
                "current_index": len(frames) - 1,
                "loop": False,
                "frames": frames,
            }

        return descriptor
