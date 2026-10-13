"""EUMETSAT EUMETView observed-satellite provider for WeatherRouter."""

from __future__ import annotations

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

_WMS = "https://view.eumetsat.int/geoserver/wms"
_LAYER = "msg_fes:rgb_eview"
_CAPABILITY_ID = "satellite_clouds"
_MAX_FRAMES = 24

_CAPABILITIES = (
    CapabilityInfo(
        _CAPABILITY_ID,
        "EUMETSAT · Meteosat European HRV RGB",
        None,
        "observation",
        "raster_tile",
    ),
)


class EumetViewProvider:
    """EUMETSAT EUMETView WMS adapter for European Meteosat imagery."""

    id = "eumetview"
    name = "EUMETSAT EUMETView"

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        """Return the initial European observed-satellite capability."""
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        """Return explanatory metadata for the generic provider info UI."""
        return ProviderInfo(
            summary=(
                "EUMETSAT EUMETView liefert Meteosat-Bildprodukte über einen "
                "öffentlichen WMS und ist WeatherRouters hochfrequente Satellitenquelle "
                "für Europa."
            ),
            coverage="Europa / Meteosat-Sichtbereich",
            strengths=(
                "für Europa sehr gut geeignete Meteosat-Abdeckung",
                "hochfrequente Beobachtungsframes",
                "Tag-/Nacht-Wolkenprodukt",
            ),
            limitations=(
                "regionaler Satellitendienst statt globalem Vollbild",
                "Darstellung und Zeitachse hängen vom jeweiligen EUMETView-Produkt ab",
            ),
            documentation_url="https://view.eumetsat.int/",
            attribution="EUMETSAT",
            services=(
                {"name": "Meteosat European HRV RGB", "status": "integriert", "note": "Europa · Beobachtung"},
            ),
        )

    async def async_get_coverage(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Return machine-readable geographic coverage from EUMETView WMS metadata."""
        if capability_id != _CAPABILITY_ID:
            raise ValueError(f"Unsupported EUMETView coverage capability: {capability_id}")
        root = await async_capabilities(hass, _WMS)
        coverage = wms_layer_geographic_coverage(root, _LAYER)
        if coverage is None:
            raise ValueError(
                f"EUMETView WMS has no machine-readable geographic coverage: {_LAYER}"
            )
        result = dict(coverage)
        result["coverage_metadata_scope"] = "layer_specific_wms"
        result["provider_metadata_source"] = "EUMETView WMS GetCapabilities"
        result["endpoint_host"] = urlsplit(_WMS).hostname
        return result

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        """Return the public EUMETView WMS destination."""
        return (
            NetworkTargetInfo(
                purpose="observed_satellite_wms",
                scheme="https",
                host="view.eumetsat.int",
                port=443,
                target_type="wms",
                required=True,
                capabilities=(_CAPABILITY_ID,),
                note=(
                    "EUMETView WMS für Meteosat-Bildprodukte. "
                    "Der initiale WeatherRouter-Layer ist European HRV RGB."
                ),
            ),
        )

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        """Return one secret-free EUMETView capability snapshot."""
        if capability_id not in {None, _CAPABILITY_ID}:
            return {
                "ok": False,
                "stage": "capability_selection",
                "error": {
                    "type": "ValueError",
                    "message": f"Unsupported EUMETView capability: {capability_id}",
                },
            }

        attempts: list[dict[str, Any]] = []
        try:
            root = await async_capabilities(hass, _WMS, attempts=attempts)
            names = named_layer_names(root)
            present = _LAYER in set(names)
            now = datetime.now(timezone.utc)
            raw_times: list[datetime] = []
            declared_default: str | None = None
            if present:
                raw_times, declared_default, _raw = layer_time_dimension(
                    root,
                    _LAYER,
                    now,
                )
            times = trim_observation_times(raw_times, _MAX_FRAMES)
            styles = layer_style_metadata(root, _LAYER) if present else {}
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
            "ok": present,
            "stage": "layer_discovery",
            "attempts": attempts,
            "service": {
                "wms_version": root.attrib.get("version"),
                "named_layer_count": len(names),
                "projection": "EPSG:3857",
            },
            "layers": [
                {
                    "capability": _CAPABILITY_ID,
                    "expected_layer": _LAYER,
                    "present": present,
                    "source_class": "observation",
                    "time_dimension": {
                        "raw_count": len(raw_times),
                        "trimmed_count": len(times),
                        "first": iso_wms(raw_times[0]) if raw_times else None,
                        "last": iso_wms(raw_times[-1]) if raw_times else None,
                        "declared_default": declared_default,
                    },
                    "style_metadata": styles,
                }
            ],
            "missing_capabilities": [] if present else [_CAPABILITY_ID],
        }

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        """Return European HRV RGB imagery through the generic WMS path."""
        if capability_id != _CAPABILITY_ID:
            raise ValueError(f"Unsupported EUMETView capability: {capability_id}")

        root = await async_capabilities(hass, _WMS)
        now = datetime.now(timezone.utc)
        raw_times, declared_default, _raw = layer_time_dimension(root, _LAYER, now)
        times = trim_observation_times(raw_times, _MAX_FRAMES)
        styles = layer_style_metadata(root, _LAYER)
        style_name = styles.get("default_style")

        frames = [
            {
                "time": int(value.timestamp()),
                "tile_url": tile_url(
                    _WMS,
                    _LAYER,
                    value,
                    time_mode="datetime",
                    style_name=style_name,
                ),
                "kind": "observation",
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
                _LAYER,
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
            "source_class": "observation",
            "render_mode": "raster_tile",
            "frame_time": selected["time"] if selected else None,
            "tile_url": current_tile_url,
            "tile_size": 256,
            "max_zoom": 9,
            "default_opacity": 0.84,
            "attribution": (
                'Imagery: <a href="https://www.eumetsat.int/" '
                'target="_blank" rel="noopener noreferrer">EUMETSAT</a>'
            ),
            "network_hosts": [host] if host else [],
            "provider_metadata": {
                "service": "WMS",
                "layer": _LAYER,
                "projection": "EPSG:3857",
                "capabilities_default": declared_default,
                "default_style": style_name,
                "styles": styles.get("styles", []),
                "latest_available": iso_wms(selected_time) if selected_time else None,
            },
        }

        legend_url = styles.get("legend_url")
        if legend_url:
            descriptor["legend"] = {
                "title": "EUMETSAT · Meteosat European HRV RGB",
                "url": legend_url,
                "style": style_name,
            }

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
