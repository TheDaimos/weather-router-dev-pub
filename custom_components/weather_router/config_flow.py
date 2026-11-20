"""Config flow for WeatherRouter."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
import voluptuous as vol

from .const import CONF_SHOW_SIDEBAR_PANEL, DOMAIN, NAME

SIDEBAR_OPTIONS_SCHEMA = vol.Schema({
    vol.Required(CONF_SHOW_SIDEBAR_PANEL, default=True): bool,
})


class WeatherRouterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a WeatherRouter config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "WeatherRouterOptionsFlow":
        """Provide native integration settings (the gear icon)."""
        return WeatherRouterOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Create the single WeatherRouter Config Entry."""
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})

        return self.async_show_form(step_id="user")


class WeatherRouterOptionsFlow(OptionsFlowWithReload):
    """Manage WeatherRouter sidebar visibility without changing provider settings."""

    async def async_step_init(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Update sidebar visibility and reload the integration."""
        if user_input is not None:
            return self.async_create_entry(data={
                **self.config_entry.options,
                CONF_SHOW_SIDEBAR_PANEL: user_input[CONF_SHOW_SIDEBAR_PANEL],
            })

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                SIDEBAR_OPTIONS_SCHEMA, self.config_entry.options
            ),
        )
