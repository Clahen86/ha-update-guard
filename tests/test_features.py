"""Safe update, going back, GitHub reports, skipped versions, marketplace, dead projects and the panel."""

import re

from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from homeassistant.components.update import UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest

from custom_components.update_guard.const import DOMAIN
from custom_components.update_guard.coordinator import _overall

from .test_init import _mock_github

CARD = "https://github.com/someone/cool_card/releases/tag/v2.1.0"
API = "https://api.github.com"


def _card_releases(aioclient_mock):
    aioclient_mock.get(
        f"{API}/repos/someone/cool_card/releases",
        json=[
            {"tag_name": "v2.1.0", "published_at": "2026-11-01T10:00:00Z",
             "body": "## Features\n- Added support for the `cool_mode` attribute\n- Fixes CVE-2026-1234 in the editor"},
            {"tag_name": "v2.0.0", "published_at": "2026-10-20T10:00:00Z",
             "body": "## ⚠ Breaking changes\n- The `old_option` option was removed"},
            {"tag_name": "v1.9.0", "published_at": "2026-10-01T10:00:00Z", "body": "- Old stuff"},
        ],
    )
    aioclient_mock.get(
        f"{API}/search/issues",
        json={"total_count": 3, "items": [{"title": "Broken after v2.1.0"}, {"title": "Card blank in 2.1.0"}]},
    )


async def _store_update(hass, platform="marketplace", category="plugin", features=23):
    entry = MockConfigEntry(domain=platform, data={})
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(platform, "939")}, name="Cool card",
        manufacturer="someone", model=category,
    )
    er.async_get(hass).async_get_or_create(
        "update", platform, "939", suggested_object_id="cool_card_update", device_id=device.id,
        config_entry=entry,
    )
    hass.states.async_set(
        "update.cool_card_update",
        "on",
        {"installed_version": "v1.9.0", "latest_version": "v2.1.0", "release_url": CARD,
         "supported_features": features, "friendly_name": "Cool card"},
    )


async def _setup(hass, options=None):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_marketplace_skipped_versions_reports_security(hass: HomeAssistant, aioclient_mock) -> None:
    _card_releases(aioclient_mock)
    _mock_github(aioclient_mock)
    await _store_update(hass)
    await _setup(hass)
    update = hass.states.get("sensor.update_guard_assessment").attributes["updates"][0]
    assert update["kind"] == "hacs" and update["category"] == "plugin"
    # Both versions are read: the breaking change in 2.0.0 is found although 2.1.0 is the newest.
    assert update["skipped"] == ["v2.1.0", "v2.0.0"]
    assert any("old_option" in f["text"] for f in update["findings"])
    assert update["security"]
    reports = [f for f in update["findings"] if f["source"] == "reports"]
    assert reports and "3" in reports[0]["text"] and "Broken after" in reports[0]["text"]
    assert update["level"] == "check"


async def test_news_for_you(hass: HomeAssistant, aioclient_mock) -> None:
    _card_releases(aioclient_mock)
    _mock_github(aioclient_mock)
    await _store_update(hass, platform="esphome_fake", category=None)
    # Firmware of a device whose entity has the attribute the new feature is about.
    registry = er.async_get(hass)
    update_entry = registry.async_get("update.cool_card_update")
    registry.async_get_or_create("sensor", "esphome_fake", "s1", suggested_object_id="mode",
                                 device_id=update_entry.device_id)
    hass.states.async_set("sensor.mode", "1", {"cool_mode": "on"})
    await _setup(hass)
    update = hass.states.get("sensor.update_guard_assessment").attributes["updates"][0]
    assert update["news"] and "cool_mode" in update["news"][0]


def test_overall_ignores_firmware_without_notes() -> None:
    firmware = {"level": "unclear", "kind": "other", "notes_missing": True}
    card = {"level": "safe", "kind": "hacs", "notes_missing": False}
    assert _overall([firmware, card]) == "safe"
    assert _overall([firmware]) == "unclear"
    assert _overall([{"level": "unclear", "kind": "core", "notes_missing": True}, card]) == "unclear"


async def test_safe_update(hass: HomeAssistant, aioclient_mock) -> None:
    _card_releases(aioclient_mock)
    _mock_github(aioclient_mock)
    await _store_update(hass)
    hass.states.async_set("switch.washer", "on", {"friendly_name": "Vaskemaskine"})
    entry = await _setup(hass, {"blockers": ["switch.washer"]})
    # After setup: the real update component is loaded with Update Guard.
    installs = async_mock_service(hass, "update", "install")

    # The washing machine runs: it waits.
    response = await hass.services.async_call(
        DOMAIN, "safe_update", {"entity_id": "update.cool_card_update"}, blocking=True, return_response=True
    )
    assert response == {"result": "waiting"} and not installs
    assert "update.cool_card_update" in hass.states.get("sensor.update_guard_assessment").attributes["planned"]

    # Off: installed, without a backup (a card goes back by installing the old version).
    hass.states.async_set("switch.washer", "off")
    response = await hass.services.async_call(
        DOMAIN, "safe_update", {"entity_id": "update.cool_card_update"}, blocking=True, return_response=True
    )
    assert response == {"result": "installed"}
    await hass.async_block_till_done()
    assert installs[-1].data == {"entity_id": "update.cool_card_update"}

    # Tonight.
    response = await hass.services.async_call(
        DOMAIN, "safe_update", {"entity_id": "update.cool_card_update", "when": "tonight"}, blocking=True,
        return_response=True,
    )
    assert response == {"result": "planned"}

    # Something to wait with is refused, unless forced.
    coordinator = entry.runtime_data
    coordinator.data["updates"][0]["level"] = "wait"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "safe_update", {"entity_id": "update.cool_card_update"}, blocking=True)
    await hass.services.async_call(
        DOMAIN, "safe_update", {"entity_id": "update.cool_card_update", "force": True}, blocking=True
    )


async def test_backup_only_when_needed(hass: HomeAssistant, aioclient_mock) -> None:
    from datetime import timedelta
    from unittest.mock import MagicMock, patch

    from homeassistant.util import dt as dt_util

    _mock_github(aioclient_mock)
    entry = await _setup(hass)
    installer = entry.runtime_data.installer
    core = {"kind": "core"}
    config = MagicMock()
    with patch("homeassistant.components.backup.async_get_manager") as manager:
        manager.return_value.config.data = config
        config.last_completed_automatic_backup = dt_util.utcnow() - timedelta(hours=5)
        config.last_attempted_automatic_backup = config.last_completed_automatic_backup
        assert not installer.backup_needed(core)  # last night's backup covers it
        config.last_attempted_automatic_backup = dt_util.utcnow()
        assert installer.backup_needed(core)  # last night's backup failed
        config.last_completed_automatic_backup = dt_util.utcnow() - timedelta(days=3)
        config.last_attempted_automatic_backup = config.last_completed_automatic_backup
        assert installer.backup_needed(core)  # too old
    assert not installer.backup_needed({"kind": "hacs"})


async def test_rollback_flow(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.components.repairs import DOMAIN as REPAIRS
    from homeassistant.setup import async_setup_component

    from custom_components.update_guard.repairs import async_create_fix_flow

    _card_releases(aioclient_mock)
    _mock_github(aioclient_mock)
    await _store_update(hass, features=int(UpdateEntityFeature.INSTALL | UpdateEntityFeature.SPECIFIC_VERSION))
    await _setup(hass)
    installs = async_mock_service(hass, "update", "install")
    assert await async_setup_component(hass, REPAIRS, {})
    flow = await async_create_fix_flow(
        hass, "after_1", {"rollback": [{"entity_id": "update.cool_card_update", "version": "v1.9.0", "kind": "hacs",
                                         "name": "Cool card", "slug": None}]}
    )
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["type"] == "form" and "v1.9.0" in result["description_placeholders"]["names"]
    result = await flow.async_step_confirm({})
    assert result["type"] == "create_entry"
    assert installs[-1].data == {"entity_id": "update.cool_card_update", "version": "v1.9.0"}


async def test_core_wait_for_fix_and_compat(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.util import dt as dt_util

    now = dt_util.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    aioclient_mock.get(
        f"{API}/repos/home-assistant/core/releases/tags/2026.10.0",
        json={"body": "https://www.home-assistant.io/blog/2026/10/07/release-202610/", "published_at": now},
    )
    aioclient_mock.get(f"{API}/repos/home-assistant/core/releases", json=[])
    aioclient_mock.get(
        re.compile(r"https://api\.github\.com/search/issues.*"),
        json={"total_count": 1, "items": [{"title": "Broken in 2026.10",
                                           "repository_url": f"{API}/repos/someone/cool_card"}]},
    )
    _mock_github(aioclient_mock)
    await _store_update(hass)
    hass.states.async_set("update.cool_card_update", "off", {"installed_version": "v2.1.0",
                                                             "latest_version": "v2.1.0", "release_url": CARD})
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "update", "hassio", "home_assistant_core_version_latest", suggested_object_id="home_assistant_core_update"
    )
    hass.states.async_set(
        "update.home_assistant_core_update", "on", {"installed_version": "2026.9.3", "latest_version": "2026.10.0"}
    )
    hass.config.components.add("mqtt")
    await _setup(hass, {"wait_for_fix": True})
    core = hass.states.get("sensor.update_guard_assessment").attributes["updates"][0]
    texts = " | ".join(f["text"] for f in core["findings"])
    assert "2026.10.1" in texts
    assert any(f["title"] == "Cool card" and f["source"] == "reports" for f in core["findings"])
    assert core["level"] in ("check", "wait")


async def test_dead_projects_and_panel(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{API}/repos/someone/cool_card", json={"archived": True, "pushed_at": "2020-01-01T00:00:00Z"})
    _card_releases(aioclient_mock)
    _mock_github(aioclient_mock)
    await _store_update(hass)
    await _setup(hass)
    dead = hass.states.get("sensor.update_guard_assessment").attributes["dead"]
    assert dead and dead[0]["name"] == "Cool card" and "archived" in dead[0]["why"]
    assert "update-guard" in hass.data["frontend_panels"]


async def test_settings_from_the_panel(hass: HomeAssistant, aioclient_mock, hass_ws_client) -> None:
    _mock_github(aioclient_mock)
    async_mock_service(hass, "notify", "mobile_app_phone")
    hass.states.async_set("switch.vaskemaskine", "off", {"friendly_name": "Vaskemaskine"})
    entry = await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "update_guard/settings"})
    result = (await client.receive_json())["result"]
    assert "notify.mobile_app_phone" in result["notify_services"]
    assert result["suggested_blockers"] == ["switch.vaskemaskine"]
    assert result["options"]["notify_level"] == "safe"

    await client.send_json_auto_id(
        {"type": "update_guard/save_settings", "notify": ["notify.mobile_app_phone"], "blockers": ["switch.vaskemaskine"],
         "wait_for_fix": True}
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert entry.options["notify"] == ["notify.mobile_app_phone"] and entry.options["wait_for_fix"] is True
    # Saved without a reload: the same coordinator keeps running.
    assert entry.runtime_data.installer.busy() == []
    await client.send_json_auto_id({"type": "update_guard/save_settings", "ai_task": None})
    assert (await client.receive_json())["success"]
