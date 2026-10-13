"""Official ECCC/MSC GeoMet observed-lightning density provider."""

from __future__ import annotations

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
    tile_url,
    trim_observation_times,
)

_WMS = "https://geo.weather.gc.ca/geomet"
_LAYER = "Lightning_2.5km_Density"
_CAPABILITY_ID = "lightning_density_2_5km"
_PROVIDER_REVISION = "wr-0.10.76-eccc-lightning-1"
_MAX_FRAMES = 18

_CAPABILITIES = (
    CapabilityInfo(
        id=_CAPABILITY_ID,
        name="ECCC/MSC · Blitzdichte 2,5 km",
        unit="km⁻² min⁻¹",
        source_class="observation",
        render_mode="raster_tile",
        description=(
            "Observed lightning flash density from the Canadian Lightning Detection "
            "Network, aggregated every 10 minutes on an approximately 2.5 km grid."
        ),
        coverage="Most of Canada and up to roughly 250 km from Canadian land/sea borders",
        temporal_resolution="10-minute observed accumulation",
        strengths=(
            "official Environment and Climate Change Canada source",
            "Canadian Lightning Detection Network observations",
            "cloud-to-ground and intra-cloud observations",
            "public operational GeoMet WMS",
        ),
        limitations=(
            "density raster, not individual strike points",
            "coverage is Canada-centric",
            "data beyond roughly 250 km from Canadian borders are masked",
            "observation, not an official warning",
        ),
        documentation_url="https://eccc-msc.github.io/open-data/msc-data/lightning/readme_lightning-geomet_en/",
    ),
)


class EcccLightningProvider:
    """ECCC/MSC GeoMet lightning-density WMS adapter."""

    id = "eccc_lightning"
    name = "ECCC/MSC · Lightning Density"
    router_display_group = "thunderstorm"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Official observed lightning-density product from the Canadian "
                "Lightning Detection Network through MSC GeoMet."
            ),
            coverage="Most of Canada and adjacent areas",
            strengths=(
                "official Canadian weather service source",
                "public WMS without API key",
                "10-minute observed flash-density updates",
                "cloud-to-ground and intra-cloud observations",
            ),
            limitations=(
                "2.5 km density grid rather than individual lightning coordinates",
                "Canada-centred coverage",
                "masked beyond approximately 250 km from Canadian borders",
            ),
            documentation_url="https://eccc-msc.github.io/open-data/msc-data/lightning/readme_lightning-geomet_en/",
            attribution="Environment and Climate Change Canada / Meteorological Service of Canada",
            services=(
                {
                    "name": "MSC GeoMet · Lightning_2.5km_Density",
                    "status": "integriert",
                    "note": "WMS · observed flash density · 10-minute aggregation",
                },
                {
                    "name": "MSC Datamart · GeoTIFF",
                    "status": "katalogisiert",
                    "note": "HTTPS/AMQP GeoTIFF distribution",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="official_observed_lightning_density",
                scheme="https",
                host="geo.weather.gc.ca",
                port=443,
                target_type="wms",
                required=True,
                capabilities=(_CAPABILITY_ID,),
                note="MSC GeoMet Lightning_2.5km_Density WMS.",
            ),
        )

    async def async_diagnostics(
        self,
        hass: HomeAssistant,
        capability_id: str | None = None,
    ) -> dict[str, Any]:
        if capability_id not in {None, _CAPABILITY_ID}:
            return {
                "ok": False,
                "stage": "capability_selection",
                "provider_revision": _PROVIDER_REVISION,
            }

        attempts: list[dict[str, Any]] = []
        try:
            root = await async_capabilities(hass, _WMS, attempts=attempts)
            times, declared_default, _raw = layer_time_dimension(
                root,
                _LAYER,
                datetime.now(timezone.utc),
            )
            styles = layer_style_metadata(root, _LAYER)
        except Exception as err:  # noqa: BLE001
            return {
                "ok": False,
                "stage": "eccc_lightning_geomet",
                "provider_revision": _PROVIDER_REVISION,
                "attempts": attempts,
                "error": {"type": type(err).__name__, "message": str(err)},
            }

        return {
            "ok": True,
            "stage": "eccc_lightning_geomet",
            "provider_revision": _PROVIDER_REVISION,
            "layer": _LAYER,
            "time_count": len(times),
            "latest": iso_wms(times[-1]) if times else None,
            "declared_default": declared_default,
            "styles": styles.get("styles", []),
            "official_source": True,
            "product_semantics": "observed_flash_density",
            "unit": "km^-2 min^-1",
        }

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        if capability_id != _CAPABILITY_ID:
            raise ValueError(f"Unsupported ECCC lightning capability: {capability_id}")

        root = await async_capabilities(hass, _WMS)
        now = datetime.now(timezone.utc)
        raw_times, declared_default, _raw = layer_time_dimension(root, _LAYER, now)
        times = trim_observation_times(raw_times, _MAX_FRAMES)
        styles = layer_style_metadata(root, _LAYER)
        style_name = styles.get("default_style") or "Lightning"

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
            if selected
            else tile_url(_WMS, _LAYER, None, style_name=style_name)
        )
        host = urlsplit(_WMS).hostname
        descriptor: dict[str, Any] = {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "observation",
            "render_mode": "raster_tile",
            "frame_time": selected["time"] if selected else None,
            "tile_url": current_tile_url,
            "tile_size": 256,
            "max_zoom": 9,
            "default_opacity": 0.84,
            "attribution": (
                'Lightning observations: <a href="https://weather.gc.ca/" '
                'target="_blank" rel="noopener noreferrer">Environment and Climate Change Canada</a>'
            ),
            "network_hosts": [host] if host else [],
            "provider_metadata": {
                "service": "MSC GeoMet WMS",
                "layer": _LAYER,
                "measurement": "observed_flash_density",
                "unit": "km^-2 min^-1",
                "grid_resolution": "approximately 2.5 km",
                "accumulation_period": "10 minutes",
                "includes_cloud_to_ground": True,
                "includes_intra_cloud": True,
                "individual_strike_points": False,
                "official_source": True,
                "capabilities_default": declared_default,
                "latest_available": iso_wms(selected_time) if selected_time else None,
            },
        }
        legend_url = styles.get("legend_url")
        if legend_url:
            descriptor["legend"] = {
                "title": "ECCC/MSC · Blitzdichte",
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
