"""WeatherRouter Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from functools import partial
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
    CONF_SHOW_SIDEBAR_PANEL,
    DEFAULT_OPTIONS,
    DOMAIN,
    INTEGRATION_VERSION,
    LOCATION_DOMAINS,
    PLATFORMS,
    ROUTER_DOMAINS,
)
from .consumer_api import async_register as async_register_consumer_api
from .consumer_raster_mosaic_api import async_register as async_register_consumer_mosaic_api
from .consumer_wind_field_api import async_register as async_register_consumer_wind_field_api
from .consumer_temperature_field_api import async_register as async_register_consumer_temperature_field_api
from .consumer_synoptic_api import async_register as async_register_consumer_synoptic_api
from .consumer_api_monitor_ws import async_register as async_register_monitor_api, async_unload as async_unload_monitor
from .consumer_profiles import validate_consumer_profiles
from .consumer_event_time_policy import _declared_policies
from .extensions import async_notify_routing_changed, async_setup_extensions, async_unload_extensions
from .websocket_api import async_register as async_register_websocket_api
from .routing_diagnostics import async_register as async_register_routing_diagnostics_api
from .opera_ha_core_runtime_ws import async_register as async_register_opera_core_runtime

LAB_URL_PATH = "weather-router-lab"
LAB_STATIC_URL = "/weather_router_static"
LAB_FRONTEND_REV = "2026-11-20-weather-router-final-v100"


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
    if not isinstance(options[CONF_SHOW_SIDEBAR_PANEL], bool):
        raise ValueError("show_sidebar_panel must be boolean")

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
        sidebar_title="WeatherRouter",
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
    # Warm the strict event-time policy cache outside Home Assistant's event loop.
    # A first Consumer capability WebSocket request must never read files synchronously.
    await hass.async_add_executor_job(_declared_policies)
    # Reap only stale historical OPERA diagnostic files; never touch live jobs.
    from .opera_historical_diagnostic import cleanup_orphans
    try:
        await hass.async_add_executor_job(cleanup_orphans)
    except (OSError, ValueError):
        # A cleanup error must not prevent native-free V1/V2 from loading.
        pass
    async_register_websocket_api(hass)
    async_register_consumer_api(hass)
    async_register_consumer_mosaic_api(hass)
    async_register_consumer_wind_field_api(hass)
    async_register_consumer_temperature_field_api(hass)
    async_register_consumer_synoptic_api(hass)
    async_register_monitor_api(hass)
    async_register_routing_diagnostics_api(hass)
    async_register_opera_core_runtime(hass)
    from .opera_ring_ws import async_register as async_register_opera_ring
    async_register_opera_ring(hass)
    from .opera_settings_ws import async_register as async_register_opera_settings
    async_register_opera_settings(hass)
    from .nasa_mosaic_settings import async_register as async_register_nasa_mosaic
    async_register_nasa_mosaic(hass)
    # Existing authenticated view: installed once, with an initially closed gate.
    from .opera_rate_delivery import RateDelivery
    from .opera_tile_http import OperaTileView
    from .opera_preview_age_policy import preview_continuity_from_entries
    preview_max_age = lambda: preview_continuity_from_entries(hass.config_entries.async_entries(DOMAIN))["delivery_limit_seconds"]
    delivery = RateDelivery(max_age_seconds=preview_max_age)
    area = hass.data.setdefault(DOMAIN, {})
    from .opera_config import service_allowed
    def admin_allowed(user, product):
        entries = hass.config_entries.async_entries(DOMAIN)
        options = entries[0].options if entries else {}
        return (user is not None and product == "RATE"
                and area.get("opera_rate_delivery", {}).get("enabled") is True
                and options.get(CONF_ROUTER_ENABLED, True) is True
                and "opera" in options.get(CONF_ENABLED_PROVIDERS, ())
                and service_allowed(options, "RATE"))
    area["opera_rate_delivery"] = {
        "delivery": delivery, "registry": delivery.registry,
        "http_route_active": True, "enabled": False,
        "profile_authorizer": lambda user, query: (
            user is not None
            and isinstance(query, dict)
            and query.get("capability") == "weather.precipitation.layer"),
    }
    hass.http.register_view(OperaTileView(
        hass, registry_lookup=delivery.registry.lookup,
        is_permitted=admin_allowed,
        is_provider_enabled=lambda: any(
            "opera" in entry.options.get(CONF_ENABLED_PROVIDERS, ())
            and entry.options.get(CONF_ROUTER_ENABLED, True) is True
            and service_allowed(entry.options, "RATE")
            for entry in hass.config_entries.async_entries(DOMAIN)),
        is_enabled=lambda: area.get("opera_rate_delivery", {}).get("enabled") is True,
        is_diagnostic=delivery.registry.is_diagnostic,
        max_age_seconds=preview_max_age))
    # VIS-01: isolated, explicitly disabled on each HA restart.
    # This is not the scientific tile view and cannot be enabled by updates.
    from .opera_preview_tile import OperaPreviewTileView
    # Preserve an explicit administrator opt-in through config-entry/panel reloads.
    # hass.data is process-local; live Config Entry options determine the gate.
    preview_state = area.setdefault("opera_preview", {"http_route_active": True})
    preview_state["http_route_active"] = True
    def preview_allowed():
        return any(entry.options.get("opera_dev_preview_enabled") is True
                   and service_allowed(entry.options, "RATE")
                   for entry in hass.config_entries.async_entries(DOMAIN))
    hass.http.register_view(OperaPreviewTileView(
        hass, registry_lookup=delivery.registry.lookup,
        is_diagnostic=delivery.registry.is_diagnostic,
        enabled=lambda: preview_allowed(),
        max_age_seconds=preview_max_age,
        provider_enabled=lambda: any(
            "opera" in entry.options.get(CONF_ENABLED_PROVIDERS, ())
            and entry.options.get(CONF_ROUTER_ENABLED, True) is True
            for entry in hass.config_entries.async_entries(DOMAIN)),
        permitted=lambda user, product: (
            getattr(user, "is_admin", False) is True
            and product == "RATE"
            and preview_allowed())))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WeatherRouterConfigEntry) -> bool:
    """Set up WeatherRouter from a Config Entry."""
    try:
        options = _options_with_defaults(dict(entry.options))
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigEntryError(f"Invalid WeatherRouter options: {err}") from err

    if options != entry.options:
        hass.config_entries.async_update_entry(entry, options=options)

    from .diagnostic_center import record as d2_record
    d2_record(hass, category="runtime", outcome="started", details={"ready": False})
    entry.runtime_data = WeatherRouterRuntimeData(hass=hass, entry=entry)
    # Restore the administrator's experimental preview choice after a full
    # HA restart and after a Config Entry reload. Scientific gates remain closed.
    preview = hass.data.setdefault(DOMAIN, {}).setdefault(
        "opera_preview", {"enabled": False, "http_route_active": True})

    await async_setup_extensions(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Restore administrator-selected recording on the server, independent of a UI.
    # Home Assistant Store uses atomic writes in persistent .storage.
    from homeassistant.helpers.storage import Store
    from .consumer_api_monitor import get_monitor
    api_monitor_store = Store(hass, 1, "weather_router_api_monitor")
    api_monitor = get_monitor(hass)
    try:
        saved_api = await api_monitor_store.async_load()
        api_monitor.restore(saved_api)
    except (OSError, ValueError, TypeError):
        api_monitor.restore(None)
    api_monitor._changed = lambda: api_monitor_store.async_delay_save(
        api_monitor.persistable, 2.0)
    hass.data.setdefault(DOMAIN, {})["api_monitor_persistent_store"] = api_monitor_store
    if options[CONF_SHOW_SIDEBAR_PANEL]:
        await _async_register_lab_panel(hass)
    else:
        frontend.async_remove_panel(hass, LAB_URL_PATH, warn_if_unknown=False)
    # Opt-in store foundation: executor-only filesystem initialization, no S3 polling.
    from .opera_ring_buffer import OperaRingBuffer
    ring_root = Path(hass.config.path(".storage", "weather_router_opera_ring"))
    try:
        ring = await hass.async_add_executor_job(OperaRingBuffer, ring_root)
        recovery = await hass.async_add_executor_job(ring.recover)
    except (OSError, ValueError):
        # A failed optional store must not take Consumer V1/V2 offline.
        ring = None
        recovery = None
    hass.data.setdefault(DOMAIN, {})["opera_ring_buffer"] = {
        "store": ring, "recovery": recovery, "monitor_enabled": (ring is not None),
        "poll_interval_seconds": (options.get("opera_ring_poll_seconds") if type(options.get("opera_ring_poll_seconds")) is int and options.get("opera_ring_poll_seconds") in (15, 20, 30, 60) else 30),
        "historical_http_enabled": False, "scientific_approved": False,
    }
    ring_state = hass.data.get(DOMAIN, {}).get("opera_ring_buffer", {})
    if ring_state.get("store") is not None:
        from .opera_monitor import OperaMonitor
        monitor = OperaMonitor(
            hass, ring_state["store"],
            enabled=ring_state.get("monitor_enabled") is True,
            interval=ring_state.get("poll_interval_seconds", 30))
        ring_state["monitor"] = monitor
        await monitor.start()
    stage = hass.data.get(DOMAIN, {}).get("opera_rate_delivery", {})
    if stage:
        stage["enabled"] = True
        if ring_state.get("store") is not None:
            from .opera_ring_rate_bridge import RingRateBridge
            from .opera_preview_age_policy import preview_continuity_from_entries
            from .opera_rate_scoped_approval import admit_current_rate
            bridge = RingRateBridge(
                ring=ring_state["store"], delivery=stage["delivery"],
                trusted_admission=admit_current_rate,
                age_limit=lambda: preview_continuity_from_entries(
                    hass.config_entries.async_entries(DOMAIN))["delivery_limit_seconds"])
            ring_state["rate_bridge"] = bridge
            from .opera_config import service_allowed
            options = entry.options
            allowed = (options.get(CONF_ROUTER_ENABLED, True) is True
                       and "opera" in options.get(CONF_ENABLED_PROVIDERS, ())
                       and service_allowed(options, "RATE"))
            try:
                ring_state["last_rate_stage"] = await hass.async_add_executor_job(
                    partial(bridge.stage_latest, allowed=allowed))
            except (OSError, ValueError):
                ring_state["last_rate_stage"] = {
                    "status": "rate_stage_failed", "scientific_status": "UNVERIFIED"}

    d2_record(hass, category="runtime", outcome="success", details={"ready": True})
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WeatherRouterConfigEntry) -> bool:
    """Unload WeatherRouter cleanly, including its development Lab panel."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        nasa_job = hass.data.get(DOMAIN, {}).pop("nasa_metadata_preparation", None)
        if nasa_job is not None:
            nasa_job.close()
        ring_state = hass.data.get(DOMAIN, {}).get("opera_ring_buffer", {})
        monitor = ring_state.get("monitor")
        if monitor is not None:
            await monitor.stop()
        stage = hass.data.get(DOMAIN, {}).get("opera_rate_delivery", {})
        if stage:
            stage["enabled"] = False
            stage["delivery"].reset()
            from .diagnostic_center import record as d2_record
            d2_record(hass, category="raster", outcome="unloaded", details={"frame_count": 0})
        hass.data.get(DOMAIN, {}).pop("opera_ring_buffer", None)
        await async_unload_extensions(hass, entry)
        async_unload_monitor(hass)
        frontend.async_remove_panel(hass, LAB_URL_PATH, warn_if_unknown=False)
        from .diagnostic_center import record as d2_record
        d2_record(hass, category="runtime", outcome="unloaded", details={"ready": False})
    return unloaded
