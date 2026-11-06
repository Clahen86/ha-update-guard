"""Settings for the panel: read them, and save a change right away."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_AI,
    CONF_AUTO_SAFE,
    CONF_BLOCKERS,
    CONF_NOTIFY,
    CONF_NOTIFY_LEVEL,
    CONF_WAIT_FIX,
    DOMAIN,
    NOTIFY_ALL,
    NOTIFY_LEVELS,
)

# Services that are not a phone or a list of phones.
SKIP_NOTIFY = {"notify", "send_message", "persistent_notification"}
# Words in a name that suggest something you don't want to interrupt with a restart.
_BUSY_WORDS = (
    "vaskemaskine", "opvask", "tørretumbler", "tørre", "lader", "ladebox", "oplad", "charg", "wallbox", "washer",
    "washing", "dishwasher", "dryer", "ovn", "oven", "3d", "printer", "keba", "easee", "zaptec",
)
_BUSY_DOMAINS = ("switch", "binary_sensor", "sensor", "input_boolean", "media_player", "vacuum")


@callback
def async_setup(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_settings)
    websocket_api.async_register_command(hass, ws_save_settings)


def notify_services(hass: HomeAssistant, current: list[str]) -> list[str]:
    services = {f"notify.{n}" for n in hass.services.async_services_for_domain("notify") if n not in SKIP_NOTIFY}
    return sorted(services | set(current) | {"notify.persistent_notification"})


def _entry(hass: HomeAssistant):
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0] if entries else None


def _suggestions(hass: HomeAssistant, chosen: list[str]) -> list[str]:
    """Devices that look like a washing machine, dryer or charger, for one-tap adding."""
    found = []
    for state in hass.states.async_all(_BUSY_DOMAINS):
        name = f"{state.entity_id} {state.attributes.get('friendly_name', '')}".lower()
        if state.entity_id in chosen or not any(w in name for w in _BUSY_WORDS):
            continue
        # A power or status sensor is a good sign; a battery or temperature isn't.
        if state.domain == "sensor" and state.attributes.get("device_class") not in ("power", "enum", None):
            continue
        found.append(state.entity_id)
    return sorted(found)[:12]


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "update_guard/settings"})
@callback
def ws_settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_loaded", "Update Guard isn't running")
        return
    options = entry.options
    blockers = list(options.get(CONF_BLOCKERS) or [])
    connection.send_result(
        msg["id"],
        {
            "options": {
                CONF_NOTIFY: list(options.get(CONF_NOTIFY) or []),
                CONF_NOTIFY_LEVEL: options.get(CONF_NOTIFY_LEVEL, NOTIFY_ALL),
                CONF_AI: options.get(CONF_AI),
                CONF_WAIT_FIX: bool(options.get(CONF_WAIT_FIX)),
                CONF_BLOCKERS: blockers,
                CONF_AUTO_SAFE: bool(options.get(CONF_AUTO_SAFE)),
            },
            "notify_services": notify_services(hass, list(options.get(CONF_NOTIFY) or [])),
            "ai_tasks": sorted(s.entity_id for s in hass.states.async_all("ai_task")),
            "suggested_blockers": _suggestions(hass, blockers),
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "update_guard/save_settings",
        vol.Optional(CONF_NOTIFY): [cv.string],
        vol.Optional(CONF_NOTIFY_LEVEL): vol.In(NOTIFY_LEVELS),
        vol.Optional(CONF_AI): vol.Any(None, cv.entity_domain("ai_task")),
        vol.Optional(CONF_WAIT_FIX): cv.boolean,
        vol.Optional(CONF_BLOCKERS): [cv.entity_id],
        vol.Optional(CONF_AUTO_SAFE): cv.boolean,
    }
)
@callback
def ws_save_settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    entry = _entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_loaded", "Update Guard isn't running")
        return
    options = dict(entry.options)
    for key, value in msg.items():
        if key in ("id", "type"):
            continue
        if value is None or value == "":
            options.pop(key, None)
        else:
            options[key] = value
    hass.config_entries.async_update_entry(entry, options=options)
    connection.send_result(msg["id"], {"saved": True})
