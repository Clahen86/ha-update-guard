"""Setup, sensors and repairs with fake updates."""

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from custom_components.update_guard.const import DOMAIN

from .test_notes import POST

RELEASE = "https://api.github.com/repos/home-assistant/core/releases/tags/2026.10.0"
LATEST = "https://api.github.com/repos/home-assistant/core/releases/latest"
RAW = "https://raw.githubusercontent.com/home-assistant/home-assistant.io/current/source/_posts/2026-10-07-release-202610.markdown"


def _mock_github(aioclient_mock):
    aioclient_mock.get(RELEASE, json={"body": "https://www.home-assistant.io/blog/2026/10/07/release-202610/"})
    aioclient_mock.get(LATEST, json={"tag_name": "2026.10.4"})
    aioclient_mock.get(RAW, text=POST)


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    hass.config.components.add("mqtt")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_core_update_matches_used_integrations(hass: HomeAssistant, aioclient_mock) -> None:
    _mock_github(aioclient_mock)
    er.async_get(hass).async_get_or_create(
        "update", "hassio", "home_assistant_core_version_latest", suggested_object_id="home_assistant_core_update"
    )
    hass.states.async_set(
        "update.home_assistant_core_update",
        "on",
        {"installed_version": "2026.9.3", "latest_version": "2026.10.4", "title": "Home Assistant Core"},
    )
    await _setup(hass)

    state = hass.states.get("sensor.update_guard_assessment")
    assert state.state == "check"
    core = state.attributes["updates"][0]
    assert core["kind"] == "core" and core["latest"] == "2026.10.4"
    titles = [f["title"] for f in core["findings"]]
    assert "2026.10: MQTT" in titles
    assert not any("Xbox" in t for t in titles)
    assert hass.states.get("sensor.update_guard_things_to_check").state == "1"

    issue = ir.async_get(hass).async_get_issue(DOMAIN, "risk_update.home_assistant_core_update")
    assert issue and issue.translation_key == "update_check"
    assert "MQTT" in issue.translation_placeholders["findings"]


async def test_app_changelog_and_issue_cleanup(hass: HomeAssistant, aioclient_mock) -> None:
    _mock_github(aioclient_mock)
    er.async_get(hass).async_get_or_create(
        "update", "hassio", "a0d7b954_appdaemon_version_latest", suggested_object_id="appdaemon_update"
    )
    hass.states.async_set(
        "update.appdaemon_update",
        "on",
        {
            "installed_version": "0.17.0",
            "latest_version": "0.18.0",
            "title": "AppDaemon",
            "release_summary": "- BREAKING: Python 3.11 is no longer supported\n- Bump base image",
        },
    )
    entry = await _setup(hass)

    state = hass.states.get("sensor.update_guard_assessment")
    assert state.state == "wait"
    app = state.attributes["updates"][0]
    assert app["kind"] == "app" and app["level"] == "wait"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "risk_update.appdaemon_update")

    # Once installed, the repair goes away.
    hass.states.async_set("update.appdaemon_update", "off", {"installed_version": "0.18.0", "latest_version": "0.18.0"})
    await entry.runtime_data.async_refresh()
    assert hass.states.get("sensor.update_guard_assessment").state == "none"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "risk_update.appdaemon_update") is None


async def test_check_button(hass: HomeAssistant, aioclient_mock) -> None:
    _mock_github(aioclient_mock)
    entry = await _setup(hass)
    with patch.object(entry.runtime_data, "async_refresh") as refresh:
        await hass.services.async_call("button", "press", {"entity_id": "button.update_guard_check_now"}, blocking=True)
    refresh.assert_called_once()
