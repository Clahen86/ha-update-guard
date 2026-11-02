"""Config flow for Update Guard. Notifications are set under Configure."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import CONF_NOTIFY, CONF_NOTIFY_LEVEL, DOMAIN, NOTIFY_ALL, NOTIFY_LEVELS

# Services that are not a phone or a list of phones.
_SKIP = {"notify", "send_message", "persistent_notification"}


class UpdateGuardConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Update Guard", data={})
        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UpdateGuardOptionsFlow()


class UpdateGuardOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        services = sorted(
            f"notify.{name}" for name in self.hass.services.async_services_for_domain("notify") if name not in _SKIP
        )
        # Keep a saved target in the list even if its phone is offline right now.
        current = self.config_entry.options.get(CONF_NOTIFY, [])
        services = sorted(set(services) | set(current) | {"notify.persistent_notification"})
        schema = vol.Schema(
            {
                vol.Optional(CONF_NOTIFY, default=current): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=services, multiple=True, custom_value=True)
                ),
                vol.Optional(
                    CONF_NOTIFY_LEVEL, default=self.config_entry.options.get(CONF_NOTIFY_LEVEL, NOTIFY_ALL)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=NOTIFY_LEVELS, translation_key=CONF_NOTIFY_LEVEL, mode=selector.SelectSelectorMode.LIST
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
