"""Administrative E-078 preparation switch.

This switch does NOT connect the experimental buffer to routing yet.
It persists an explicit opt-in, independent of the normal provider switch.
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WeatherRouterConfigEntry, WeatherRouterRuntimeData
from .const import CONF_BUFFER_ENABLED, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WeatherRouterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([WeatherRouterBufferPreparationSwitch(entry.runtime_data)])


class WeatherRouterBufferPreparationSwitch(SwitchEntity):
    """Switch that prepares an E-078 opt-in; data paths remain unaffected."""

    _attr_has_entity_name = True
    _attr_name = "Puffer – Vorbereitung (noch nicht verbunden)"
    _attr_unique_id = "e078_buffer_preparation"
    _attr_icon = "mdi:database-clock"

    def __init__(self, runtime: WeatherRouterRuntimeData) -> None:
        self._runtime = runtime

    @property
    def suggested_object_id(self) -> str:
        return f"{DOMAIN}_e078_buffer_preparation"

    @property
    def is_on(self) -> bool:
        return bool(self._runtime.get(CONF_BUFFER_ENABLED))

    async def async_turn_on(self, **kwargs: object) -> None:
        self._runtime.async_set(CONF_BUFFER_ENABLED, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        self._runtime.async_set(CONF_BUFFER_ENABLED, False)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        return {
            "data_path_connected": False,
            "development_stage": "E-078 isolated",
            "provider_usage_unchanged": True,
        }
