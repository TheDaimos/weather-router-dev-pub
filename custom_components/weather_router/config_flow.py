"""Config flow for WeatherRouter."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback

from .const import (DOMAIN, NAME, CONF_OPERA_PREVIEW_VALIDITY_SECONDS,
                    DEFAULT_OPERA_PREVIEW_VALIDITY_SECONDS)


class WeatherRouterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a WeatherRouter config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Allow the user to set the WR-owned temporal validity."""
        return WeatherRouterOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Create the single WeatherRouter Config Entry."""
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})

        return self.async_show_form(step_id="user")


class WeatherRouterOptionsFlow(config_entries.OptionsFlow):
    """Expose user-controlled OPERA preview validity through HA options."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input})
        current = self.config_entry.options.get(
            CONF_OPERA_PREVIEW_VALIDITY_SECONDS,
            DEFAULT_OPERA_PREVIEW_VALIDITY_SECONDS)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_OPERA_PREVIEW_VALIDITY_SECONDS, default=current):
                    vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
            }),
        )
