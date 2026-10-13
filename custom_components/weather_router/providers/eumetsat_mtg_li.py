"""Official EUMETSAT MTG Lightning Imager accumulated-flash raster provider."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from homeassistant.core import HomeAssistant

from . import CapabilityInfo, NetworkTargetInfo, ProviderInfo
from .wms_satellite import (
    async_capabilities,
    iso_wms,
    layer_style_metadata,
    layer_time_dimension,
    local_name,
    tile_url,
    trim_observation_times,
)

_WMS = "https://view.eumetsat.int/geoserver/wms"
_PROVIDER_REVISION = "wr-0.10.78-mtg-li-2"
_CAPABILITY_ID = "mtg_li_accumulated_flashes"
_MAX_FRAMES = 40

_CAPABILITIES = (
    CapabilityInfo(
        id=_CAPABILITY_ID,
        name="EUMETSAT MTG-LI · Accumulated Flashes",
        unit=None,
        source_class="satellite_observation",
        render_mode="raster_tile",
        description=(
            "Gridded accumulated lightning detections from the Meteosat Third "
            "Generation Lightning Imager via EUMETView WMS."
        ),
        coverage="Europe, Africa, Atlantic and most of the MTG full disc",
        temporal_resolution="LI accumulated product; near-real-time WMS timeline",
        strengths=(
            "official EUMETSAT source",
            "continuous geostationary lightning observation",
            "Europe/Africa/Atlantic coverage",
            "public EUMETView visualization path",
        ),
        limitations=(
            "satellite optical total-lightning product, not a ground strike network",
            "gridded accumulation rather than individual ground-strike points",
            "WMS layer naming may evolve and is discovered dynamically",
        ),
        documentation_url="https://user.eumetsat.int/resources/user-guides/mtg-li-level-2-data-guide",
    ),
)


def _layer_text(layer: ET.Element) -> tuple[str, str]:
    name = ""
    title = ""
    for child in layer:
        current = local_name(child.tag)
        if current == "Name" and not name:
            name = (child.text or "").strip()
        elif current == "Title" and not title:
            title = (child.text or "").strip()
    return name, title


def _score_li_layer(name: str, title: str) -> int:
    text = f"{name} {title}".lower()
    score = 0

    # EUMETView currently exposes the operational accumulated-flash-area
    # product as e.g. "mtg_fd:li_afa" / "LI Accumulated Flash Area ...".
    # Treat that explicit LI product signature as authoritative instead of
    # penalising the generic word "area".
    explicit_afa = (
        ":li_afa" in name.lower()
        or "li accumulated flash area" in title.lower()
        or "accumulated flash area" in text
    )
    if explicit_afa:
        score += 80

    if "lightning" in text:
        score += 20
    if "accumulated flash" in text or "accumulated_fl" in text:
        score += 40
    if "li-2-af" in text or "li_2_af" in text or "li:af" in text:
        score += 60
    if "mtg" in text or "mti" in text:
        score += 12
    if "radiance" in text:
        score -= 18
    if "area" in text and not explicit_afa:
        score -= 18
    if "event" in text or "group" in text:
        score -= 10
    return score


def _discover_layer(root: ET.Element) -> tuple[str, str]:
    candidates: list[tuple[int, str, str]] = []
    for element in root.iter():
        if local_name(element.tag) != "Layer":
            continue
        name, title = _layer_text(element)
        if not name:
            continue
        score = _score_li_layer(name, title)
        if score > 0:
            candidates.append((score, name, title))
    if not candidates:
        raise ValueError("EUMETView exposes no discoverable MTG-LI lightning layer")
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    score, name, title = candidates[0]
    if score < 35:
        raise ValueError(
            f"EUMETView LI layer discovery ambiguous: best={name!r} title={title!r} score={score}"
        )
    return name, title


class EumetsatMtgLiProvider:
    """EUMETSAT EUMETView MTG-LI raster adapter."""

    id = "eumetsat_mtg_li"
    name = "EUMETSAT · MTG Lightning Imager"
    router_display_group = "thunderstorm"
    revision = _PROVIDER_REVISION

    def capabilities(self) -> tuple[CapabilityInfo, ...]:
        return _CAPABILITIES

    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            summary=(
                "Official Meteosat Third Generation Lightning Imager data exposed "
                "through EUMETSAT's public EUMETView WMS. WeatherRouter uses the "
                "gridded accumulated-flash visualization path."
            ),
            coverage="Europe, Africa, Atlantic and most of the MTG full disc",
            strengths=(
                "official EUMETSAT satellite source",
                "continuous total-lightning monitoring",
                "strong Europe/Africa/Atlantic coverage",
                "no WeatherRouter credential required for EUMETView WMS",
            ),
            limitations=(
                "gridded satellite detection, not individual ground-strike confirmation",
                "point LI Level-2 Data Store downloads are a separate credential/licence path",
                "EUMETView layer identifiers are discovered dynamically",
            ),
            documentation_url="https://user.eumetsat.int/resources/user-guides/mtg-li-level-2-data-guide",
            attribution="EUMETSAT · Meteosat Third Generation Lightning Imager",
            services=(
                {
                    "name": "EUMETView · MTG-LI Accumulated Flashes",
                    "status": "integriert",
                    "note": "public WMS · raster_tile",
                },
                {
                    "name": "Data Store · LI Lightning Flashes",
                    "status": "katalogisiert",
                    "note": "EO:EUM:DAT:0691 · point Level-2 · credential/licence path",
                },
                {
                    "name": "Data Store · LI Accumulated Flashes",
                    "status": "katalogisiert",
                    "note": "EO:EUM:DAT:0686",
                },
            ),
        )

    def network_targets(self) -> tuple[NetworkTargetInfo, ...]:
        return (
            NetworkTargetInfo(
                purpose="official_mtg_li_accumulated_flashes",
                scheme="https",
                host="view.eumetsat.int",
                port=443,
                target_type="wms",
                required=True,
                capabilities=(_CAPABILITY_ID,),
                note="Public EUMETView WMS for MTG Lightning Imager visualization.",
            ),
            NetworkTargetInfo(
                purpose="mtg_li_catalog_metadata",
                scheme="https",
                host="api.eumetsat.int",
                port=443,
                target_type="catalog_api",
                required=False,
                capabilities=(_CAPABILITY_ID,),
                note="Official Data Store catalog; direct NRT downloads may require user credentials/licence.",
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
            layer, title = _discover_layer(root)
            times, declared_default, _raw = layer_time_dimension(
                root,
                layer,
                datetime.now(timezone.utc),
            )
        except Exception as err:  # noqa: BLE001
            return {
                "ok": False,
                "stage": "eumetview_li_discovery",
                "provider_revision": _PROVIDER_REVISION,
                "attempts": attempts,
                "error": {"type": type(err).__name__, "message": str(err)},
            }
        return {
            "ok": True,
            "stage": "eumetview_li_discovery",
            "provider_revision": _PROVIDER_REVISION,
            "layer": layer,
            "title": title,
            "time_count": len(times),
            "latest": iso_wms(times[-1]) if times else None,
            "declared_default": declared_default,
            "official_source": True,
            "product_semantics": "satellite_total_lightning_accumulation",
        }

    async def async_get_map_layer(
        self,
        hass: HomeAssistant,
        capability_id: str,
    ) -> dict[str, Any]:
        if capability_id != _CAPABILITY_ID:
            raise ValueError(f"Unsupported MTG-LI capability: {capability_id}")

        root = await async_capabilities(hass, _WMS)
        layer, title = _discover_layer(root)
        now = datetime.now(timezone.utc)
        raw_times, declared_default, _raw = layer_time_dimension(root, layer, now)
        times = trim_observation_times(raw_times, _MAX_FRAMES)
        styles = layer_style_metadata(root, layer)
        style_name = styles.get("default_style")

        frames = [
            {
                "time": int(value.timestamp()),
                "tile_url": tile_url(
                    _WMS,
                    layer,
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
            else tile_url(_WMS, layer, None, style_name=style_name)
        )
        host = urlsplit(_WMS).hostname
        descriptor: dict[str, Any] = {
            "provider": self.id,
            "provider_name": self.name,
            "provider_revision": _PROVIDER_REVISION,
            "capability": capability_id,
            "source_class": "satellite_observation",
            "render_mode": "raster_tile",
            "frame_time": selected["time"] if selected else None,
            "tile_url": current_tile_url,
            "tile_size": 256,
            "max_zoom": 8,
            "default_opacity": 0.88,
            "attribution": (
                'Lightning imagery: <a href="https://www.eumetsat.int/" '
                'target="_blank" rel="noopener noreferrer">EUMETSAT</a>'
            ),
            "network_hosts": [host] if host else [],
            "provider_metadata": {
                "instrument": "MTG Lightning Imager",
                "service": "EUMETView WMS",
                "layer": layer,
                "layer_title": title,
                "product_semantics": "satellite_total_lightning_accumulation",
                "ground_strike_confirmation": False,
                "data_store_collection_accumulated_flashes": "EO:EUM:DAT:0686",
                "data_store_collection_lightning_flashes": "EO:EUM:DAT:0691",
                "capabilities_default": declared_default,
                "latest_available": iso_wms(selected_time) if selected_time else None,
            },
        }
        legend_url = styles.get("legend_url")
        if legend_url:
            descriptor["legend"] = {
                "title": title or "EUMETSAT MTG-LI",
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
