"""Select platform for WeatherRouter."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_added_domain,
    async_track_state_removed_domain,
)

from . import WeatherRouterConfigEntry, WeatherRouterRuntimeData
from .const import (
    CONF_REFERENCE_LOCATION,
    DEFAULT_REFERENCE_LOCATION,
    DOMAIN,
    LOCATION_DISCOVERY_DOMAINS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WeatherRouterConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WeatherRouter selects."""
    async_add_entities([WeatherRouterReferenceLocationSelect(entry.runtime_data)])


class WeatherRouterReferenceLocationSelect(SelectEntity):
    """Select the router's optional default/reference Home Assistant location."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = CONF_REFERENCE_LOCATION
    _attr_unique_id = CONF_REFERENCE_LOCATION

    def __init__(self, runtime: WeatherRouterRuntimeData) -> None:
        """Initialize the reference-location select."""
        self._runtime = runtime

    @property
    def suggested_object_id(self) -> str:
        """Return the stable suggested object ID."""
        return f"{DOMAIN}_{CONF_REFERENCE_LOCATION}"

    @property
    def current_option(self) -> str:
        """Return the configured reference location."""
        return self._runtime.get(CONF_REFERENCE_LOCATION)

    @property
    def options(self) -> list[str]:
        """Return current person/zone entity IDs plus the configured value."""
        current = self.current_option
        discovered = set(
            self.hass.states.async_entity_ids(LOCATION_DISCOVERY_DOMAINS)
        )
        discovered.update((DEFAULT_REFERENCE_LOCATION, current))
        return [DEFAULT_REFERENCE_LOCATION, *sorted(discovered - {DEFAULT_REFERENCE_LOCATION})]

    async def async_select_option(self, option: str) -> None:
        """Persist a new default/reference location."""
        self._runtime.async_set(CONF_REFERENCE_LOCATION, option)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Track additions/removals of eligible Home Assistant locations."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_added_domain(
                self.hass,
                LOCATION_DISCOVERY_DOMAINS,
                self._locations_changed,
            )
        )
        self.async_on_remove(
            async_track_state_removed_domain(
                self.hass,
                LOCATION_DISCOVERY_DOMAINS,
                self._locations_changed,
            )
        )

    def _locations_changed(self, _: Event) -> None:
        """Publish changed options safely from the callback boundary."""
        self.schedule_update_ha_state()
