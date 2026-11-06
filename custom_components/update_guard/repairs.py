"""Fix flow for "stopped working after the update": go back to the version before it."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


class RollbackFlow(RepairsFlow):
    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            entries = self.hass.config_entries.async_loaded_entries(DOMAIN)
            if not entries:
                return self.async_abort(reason="not_loaded")
            installer = entries[0].runtime_data.installer
            try:
                for item in self.items:
                    await installer.async_rollback(item["entity_id"], item["version"], item["kind"], item.get("slug"))
            except HomeAssistantError:
                return self.async_abort(reason="no_rollback")
            return self.async_create_entry(data={})
        names = ", ".join(f"{i['name']} {i['version']}" for i in self.items)
        return self.async_show_form(
            step_id="confirm", data_schema=vol.Schema({}), description_placeholders={"names": names}
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    return RollbackFlow(list((data or {}).get("rollback") or []))
