"""Config flow for WeatherRouter."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult

from .const import DOMAIN, NAME


class WeatherRouterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a WeatherRouter config flow."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, object] | None = None
    ) -> ConfigFlowResult:
        """Create the single WeatherRouter Config Entry."""
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})

        return self.async_show_form(step_id="user")
