"""Installs: power sensors as blockers, the end of an install followed, plans kept over a restart."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.update_guard import install as ins


def _installer(hass, blockers=(), updates=(), auto=False):
    coordinator = SimpleNamespace(
        config_entry=SimpleNamespace(options={"blockers": list(blockers), "auto_safe": auto}),
        data={"updates": list(updates)},
        after=SimpleNamespace(count=lambda *a: None),
    )
    return ins.Installer(hass, coordinator)


async def test_power_sensor_blocker(hass: HomeAssistant) -> None:
    hass.states.async_set("sensor.washer_power", "1.3", {"unit_of_measurement": "W", "friendly_name": "Washer"})
    i = _installer(hass, ["sensor.washer_power"])
    assert i.busy() == []  # standby
    hass.states.async_set("sensor.washer_power", "850", {"unit_of_measurement": "W", "friendly_name": "Washer"})
    assert i.busy() == ["Washer"]
    hass.states.async_set("sensor.washer_power", "0.5", {"unit_of_measurement": "kW", "friendly_name": "Washer"})
    assert i.busy() == ["Washer"]


async def test_in_progress_refused(hass: HomeAssistant) -> None:
    hass.states.async_set("update.card", "on", {"in_progress": True})
    i = _installer(hass)
    with pytest.raises(ins.UpdateRefused):
        await i._install({"entity_id": "update.card", "name": "Card", "kind": "hacs", "latest": "2"})


async def test_failed_install_is_told(hass: HomeAssistant) -> None:
    async def fail(call):
        raise HomeAssistantError("backup failed")

    hass.services.async_register("update", "install", fail)
    hass.states.async_set("update.card", "on", {})
    i = _installer(hass)
    told = []
    i._tell = lambda key, **v: told.append((key, v["name"], v.get("error")))
    await i._install({"entity_id": "update.card", "name": "Card", "kind": "hacs", "latest": "2"})
    await hass.async_block_till_done()
    assert told == [("install_failed", "Card", "backup failed")]


async def test_plans_survive_and_auto_must_stay_safe(hass: HomeAssistant) -> None:
    update = {"entity_id": "update.card", "name": "Card", "kind": "hacs", "latest": "2", "level": "safe"}
    i = _installer(hass, updates=[update], auto=True)
    assert await i.async_safe_update("update.card", "tonight", auto=True) == "planned"
    await hass.async_block_till_done()
    saved = dict(i.plans)
    assert saved["update.card"]["auto"] and saved["update.card"]["version"] == "2"
    i.async_stop()

    # After a restart: the plan is back.
    j = _installer(hass, updates=[update], auto=True)
    j.store.async_load = lambda: _coro({"plans": saved})
    await j.async_load()
    assert j.planned_for() == ["update.card"]

    # Turned off: automatic plans go.
    j.cancel_auto()
    assert j.planned_for() == [] and j.plans == {}
    j.async_stop()


async def _coro(value):
    return value
