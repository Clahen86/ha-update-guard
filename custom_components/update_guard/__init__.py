"""Update Guard: tells you what a pending update will break, before you install it."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import UpdateGuardConfigEntry, UpdateGuardCoordinator

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
STATIC = "/update_guard_static"
PANEL = "update-guard"
_TITLES = {"da": "Opdateringsvagt"}

SAFE_UPDATE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("when", default="now"): vol.In(["now", "tonight"]),
        vol.Optional("force", default=False): cv.boolean,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    folder = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC, str(folder), cache_headers=False)])

    async def safe_update(call: ServiceCall) -> ServiceResponse:
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
        coordinator: UpdateGuardCoordinator = entries[0].runtime_data
        if coordinator.data is None or not any(
            u["entity_id"] == call.data["entity_id"] for u in coordinator.data["updates"]
        ):
            await coordinator.async_refresh()
        done = await coordinator.installer.async_safe_update(
            call.data["entity_id"], call.data["when"], call.data["force"]
        )
        if coordinator.data is not None:
            coordinator.data["planned"] = coordinator.installer.planned_for()
        coordinator.async_update_listeners()
        return {"result": done}

    hass.services.async_register(
        DOMAIN, "safe_update", safe_update, SAFE_UPDATE_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: UpdateGuardConfigEntry) -> bool:
    coordinator = UpdateGuardCoordinator(hass, entry)
    await coordinator.deprecations.async_load()
    await coordinator.notifier.async_load()
    await coordinator.ai.async_load()
    await coordinator.after.async_load()
    root = logging.getLogger()
    root.addHandler(coordinator.deprecations)
    entry.async_on_unload(lambda: root.removeHandler(coordinator.deprecations))
    entry.async_on_unload(coordinator.installer.async_stop)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.async_watch_updates()
    entry.async_on_unload(coordinator.after.async_start())
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_changed))
    # Version from the file's time, so the browser loads a new panel after an update.
    stamp = int((Path(__file__).parent / "frontend" / "panel.js").stat().st_mtime)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL,
        webcomponent_name="update-guard-panel",
        sidebar_title=_TITLES.get(hass.config.language.split("-")[0], "Update Guard"),
        sidebar_icon="mdi:shield-sync-outline",
        module_url=f"{STATIC}/panel.js?v={stamp}",
        require_admin=True,
    )
    return True


async def _options_changed(hass: HomeAssistant, entry: UpdateGuardConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: UpdateGuardConfigEntry) -> bool:
    frontend.async_remove_panel(hass, PANEL)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: UpdateGuardConfigEntry) -> None:
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
