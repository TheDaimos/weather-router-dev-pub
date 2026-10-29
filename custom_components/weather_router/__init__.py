"""WeatherRouter Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant, callback, valid_entity_id
from homeassistant.exceptions import ConfigEntryError, ServiceValidationError
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ENABLED_DOMAINS,
    CONF_ENABLED_PROVIDERS,
    CONF_CONSUMER_PROFILES,
    CONF_REFERENCE_LOCATION,
    CONF_ROUTER_ENABLED,
    DEFAULT_OPTIONS,
    DOMAIN,
    INTEGRATION_VERSION,
    LOCATION_DOMAINS,
    PLATFORMS,
    ROUTER_DOMAINS,
)
from .consumer_api import async_register as async_register_consumer_api
from .consumer_raster_mosaic_api import async_register as async_register_consumer_mosaic_api
from .consumer_api_monitor_ws import async_register as async_register_monitor_api, async_unload as async_unload_monitor
from .consumer_profiles import validate_consumer_profiles
from .extensions import async_notify_routing_changed, async_setup_extensions, async_unload_extensions
from .websocket_api import async_register as async_register_websocket_api
from .routing_diagnostics import async_register as async_register_routing_diagnostics_api

LAB_URL_PATH = "weather-router-lab"
LAB_STATIC_URL = "/weather_router_static"
LAB_FRONTEND_REV = "2026-10-16-api-monitor-v2-150"


def _validate_options(options: dict[str, Any]) -> None:
    """Validate the complete current WeatherRouter options model."""
    reference = options[CONF_REFERENCE_LOCATION]
    if (
        not isinstance(reference, str)
        or not valid_entity_id(reference)
        or reference.split(".", 1)[0] not in LOCATION_DOMAINS
    ):
        raise ValueError(f"Invalid reference_location: {reference!r}")

    if not isinstance(options[CONF_ROUTER_ENABLED], bool):
        raise ValueError("router_enabled must be boolean")

    domains = options[CONF_ENABLED_DOMAINS]
    if (
        not isinstance(domains, (list, tuple))
        or any(not isinstance(item, str) or item not in ROUTER_DOMAINS for item in domains)
        or len(set(domains)) != len(domains)
    ):
        raise ValueError("enabled_domains contains an unsupported router domain")

    validate_consumer_profiles(options[CONF_CONSUMER_PROFILES])

    providers = options[CONF_ENABLED_PROVIDERS]
    if (
        not isinstance(providers, (list, tuple))
        or any(
            not isinstance(item, str)
            or not item
            or not item.replace("_", "").isalnum()
            for item in providers
        )
        or len(set(providers)) != len(providers)
    ):
        raise ValueError("enabled_providers contains an invalid provider id")


def _options_with_defaults(existing: dict[str, Any]) -> dict[str, Any]:
    """Add missing defaults without overwriting existing valid choices."""
    options = {**DEFAULT_OPTIONS, **existing}
    _validate_options(options)
    return options


@dataclass(frozen=True, slots=True)
class ReferenceContext:
    """Resolved metadata for the optional default/reference location."""

    entity_id: str
    domain: str
    available: bool
    latitude: float | None
    longitude: float | None

    @property
    def has_coordinates(self) -> bool:
        """Return whether the reference currently has usable coordinates."""
        return self.latitude is not None and self.longitude is not None


@dataclass(slots=True)
class WeatherRouterRuntimeData:
    """Runtime access to WeatherRouter's Config Entry backed state."""

    hass: HomeAssistant
    entry: ConfigEntry[WeatherRouterRuntimeData]

    def get(self, key: str) -> Any:
        """Return a setting from Config Entry options."""
        return self.entry.options[key]

    @callback
    def async_set(self, key: str, value: Any) -> None:
        """Validate and persist one option atomically."""
        options = {**self.entry.options, key: value}
        try:
            _validate_options(options)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    def consumer_profiles(self) -> dict[str, dict[str, Any]]:
        """Return a defensive copy of persisted Consumer API profiles."""
        return {
            profile_id: dict(profile)
            for profile_id, profile in self.get(CONF_CONSUMER_PROFILES).items()
        }

    @callback
    def async_set_consumer_profiles(
        self,
        profiles: dict[str, dict[str, Any]],
    ) -> None:
        """Validate and persist the complete Consumer API profile set atomically."""
        validate_consumer_profiles(profiles)
        self.async_set(CONF_CONSUMER_PROFILES, profiles)

    def routing_settings(self) -> dict[str, Any]:
        """Return the persistent router eligibility settings."""
        return {
            "router_enabled": bool(self.get(CONF_ROUTER_ENABLED)),
            "enabled_domains": tuple(self.get(CONF_ENABLED_DOMAINS)),
            "enabled_providers": tuple(self.get(CONF_ENABLED_PROVIDERS)),
        }

    @callback
    def async_set_routing(
        self,
        *,
        router_enabled: bool | None = None,
        enabled_domains: list[str] | tuple[str, ...] | None = None,
        enabled_providers: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        """Persist one complete routing eligibility update atomically."""
        options = dict(self.entry.options)
        if router_enabled is not None:
            options[CONF_ROUTER_ENABLED] = router_enabled
        if enabled_domains is not None:
            options[CONF_ENABLED_DOMAINS] = list(dict.fromkeys(enabled_domains))
        if enabled_providers is not None:
            options[CONF_ENABLED_PROVIDERS] = list(dict.fromkeys(enabled_providers))
        try:
            _validate_options(options)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        self.hass.async_create_task(
            async_notify_routing_changed(self.hass, self.entry, options)
        )

    def reference_context(self) -> ReferenceContext:
        """Resolve the configured default location without inventing coordinates."""
        entity_id = self.get(CONF_REFERENCE_LOCATION)
        domain = entity_id.split(".", 1)[0]
        state = self.hass.states.get(entity_id)
        if state is None or state.state in {"unknown", "unavailable"}:
            return ReferenceContext(entity_id, domain, False, None, None)

        latitude = _coordinate(state.attributes.get(ATTR_LATITUDE), -90.0, 90.0)
        longitude = _coordinate(state.attributes.get(ATTR_LONGITUDE), -180.0, 180.0)
        return ReferenceContext(entity_id, domain, True, latitude, longitude)


def _coordinate(value: Any, minimum: float, maximum: float) -> float | None:
    """Return one finite in-range coordinate or None."""
    if isinstance(value, bool):
        return None
    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(coordinate) or not minimum <= coordinate <= maximum:
        return None
    return coordinate


type WeatherRouterConfigEntry = ConfigEntry[WeatherRouterRuntimeData]


async def _async_register_lab_panel(hass: HomeAssistant) -> None:
    """Register the admin-only diagnostic Lab panel."""
    frontend.async_remove_panel(hass, LAB_URL_PATH, warn_if_unknown=False)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=LAB_URL_PATH,
        webcomponent_name="weather-router-lab-dev-loader",
        sidebar_title="WeatherRouter Lab",
        sidebar_icon="mdi:weather-partly-cloudy",
        module_url=f"{LAB_STATIC_URL}/weather-router-lab-dev-loader.js?v={LAB_FRONTEND_REV}",
        require_admin=True,
        config={"development_lab": True, "version": INTEGRATION_VERSION, "frontend_hot_reload": True},
        handle_safe_area=True,
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register static Lab assets and the diagnostic WebSocket API once."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(LAB_STATIC_URL, str(Path(__file__).parent / "frontend"), False)]
    )
    async_register_websocket_api(hass)
    async_register_consumer_api(hass)
    async_register_consumer_mosaic_api(hass)
    async_register_monitor_api(hass)
    async_register_routing_diagnostics_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WeatherRouterConfigEntry) -> bool:
    """Set up WeatherRouter from a Config Entry."""
    try:
        options = _options_with_defaults(dict(entry.options))
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigEntryError(f"Invalid WeatherRouter options: {err}") from err

    if options != entry.options:
        hass.config_entries.async_update_entry(entry, options=options)

    # Config-entry owned lifetime: reload creates a fresh cache only after unload.
    from .opera_runtime import OperaRuntime
    opera_area = hass.data.setdefault(DOMAIN, {})
    if "opera_runtime" not in opera_area:
        opera_area["opera_runtime"] = OperaRuntime()
    entry.runtime_data = WeatherRouterRuntimeData(hass=hass, entry=entry)
    await async_setup_extensions(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_register_lab_panel(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WeatherRouterConfigEntry) -> bool:
    """Unload WeatherRouter cleanly, including its development Lab panel."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        opera_area = hass.data.get(DOMAIN, {})
        runtime = opera_area.pop("opera_runtime", None)
        if runtime is not None:
            runtime.close()  # Defers physical cache deletion until last reader lease.
        await async_unload_extensions(hass, entry)
        async_unload_monitor(hass)
        frontend.async_remove_panel(hass, LAB_URL_PATH, warn_if_unknown=False)
    return unloaded
