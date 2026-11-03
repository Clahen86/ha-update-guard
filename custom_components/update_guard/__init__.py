"""Update Guard: tells you what a pending update will break, before you install it."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .coordinator import UpdateGuardConfigEntry, UpdateGuardCoordinator

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: UpdateGuardConfigEntry) -> bool:
    coordinator = UpdateGuardCoordinator(hass, entry)
    await coordinator.deprecations.async_load()
    await coordinator.notifier.async_load()
    await coordinator.ai.async_load()
    root = logging.getLogger()
    root.addHandler(coordinator.deprecations)
    entry.async_on_unload(lambda: root.removeHandler(coordinator.deprecations))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.async_watch_updates()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_changed))
    return True


async def _options_changed(hass: HomeAssistant, entry: UpdateGuardConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: UpdateGuardConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: UpdateGuardConfigEntry) -> None:
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
