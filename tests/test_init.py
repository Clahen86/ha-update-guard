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


async def test_own_setup_logs_and_repairs(hass: HomeAssistant, aioclient_mock) -> None:
    """MQTT change is found in an automation; log warnings and repairs for 2026.10 are added."""
    import logging

    from homeassistant.setup import async_setup_component

    _mock_github(aioclient_mock)
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": {
                "alias": "Send til broker",
                "triggers": [{"trigger": "event", "event_type": "test"}],
                "actions": [{"action": "mqtt.publish", "data": {"topic": "x", "payload": "y"}}],
            }
        },
    )
    er.async_get(hass).async_get_or_create(
        "update", "hassio", "home_assistant_core_version_latest", suggested_object_id="home_assistant_core_update"
    )
    hass.states.async_set(
        "update.home_assistant_core_update", "on", {"installed_version": "2026.9.3", "latest_version": "2026.10.4"}
    )
    ir.async_create_issue(
        hass,
        "old_thing",
        "deprecated_yaml",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
        breaks_in_ha_version="2026.10.0",
    )
    ir.async_create_issue(
        hass,
        "later_thing",
        "deprecated_yaml",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="deprecated_yaml",
        breaks_in_ha_version="2027.1.0",
    )
    entry = await _setup(hass)
    logging.getLogger("homeassistant.helpers.frame").warning(
        "Detected that custom integration 'my_custom' uses x. This will stop working in Home Assistant 2026.10, please report it"
    )
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()

    core = hass.states.get("sensor.update_guard_assessment").attributes["updates"][0]
    assert core["level"] == "wait"
    by_source = {}
    for f in core["findings"]:
        by_source.setdefault(f["source"], []).append(f)
    assert [f["title"] for f in by_source["repair"]] == ["old_thing"]  # 2027.1 is not in this update
    assert by_source["log"][0]["title"] == "my_custom"
    mqtt = next(f for f in by_source["release"] if f["title"] == "2026.10: MQTT")
    assert mqtt["used_in"] == ["automation: Send til broker"]

    issue = ir.async_get(hass).async_get_issue(DOMAIN, "risk_update.home_assistant_core_update")
    assert issue.translation_key == "update_wait"
    assert "Used in: Automation: Send til broker" in issue.translation_placeholders["findings"]


async def test_hacs_needs_newer_home_assistant(hass: HomeAssistant, aioclient_mock) -> None:
    _mock_github(aioclient_mock)
    aioclient_mock.get(
        "https://raw.githubusercontent.com/someone/cool_card/v2.0.0/hacs.json", json={"homeassistant": "2099.1.0"}
    )
    er.async_get(hass).async_get_or_create("update", "hacs", "12345", suggested_object_id="cool_card_update")
    hass.states.async_set(
        "update.cool_card_update",
        "on",
        {
            "installed_version": "v1.0.0",
            "latest_version": "v2.0.0",
            "title": "Cool card",
            "release_url": "https://github.com/someone/cool_card/releases/v2.0.0",
        },
    )
    await _setup(hass)
    update = hass.states.get("sensor.update_guard_assessment").attributes["updates"][0]
    assert update["kind"] == "hacs" and update["level"] == "wait"
    assert update["findings"][0]["text"] == "Home Assistant 2099.1.0"


async def test_app_option_changes(hass: HomeAssistant, aioclient_mock) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    _mock_github(aioclient_mock)
    er.async_get(hass).async_get_or_create(
        "update", "hassio", "45df7312_zigbee2mqtt_version_latest", suggested_object_id="zigbee2mqtt_update"
    )
    hass.states.async_set(
        "update.zigbee2mqtt_update",
        "on",
        {
            "installed_version": "2.14.3-1",
            "latest_version": "3.0.0-1",
            "title": "Zigbee2MQTT",
            "release_summary": "- The `serial.adapter` option was renamed, use `adapter` under `serial`\n- Bump base image",
        },
    )
    client = MagicMock()
    client.addons.addon_info = AsyncMock(return_value=SimpleNamespace(options={"serial": {"adapter": "ember"}}))
    with patch("homeassistant.components.hassio.get_supervisor_client", return_value=client):
        await _setup(hass)
    client.addons.addon_info.assert_awaited_with("45df7312_zigbee2mqtt")
    app = hass.states.get("sensor.update_guard_assessment").attributes["updates"][0]
    assert app["level"] == "wait"
    assert app["findings"][0]["source"] == "option" and "adapter" in app["findings"][0]["title"]
    assert len(app["findings"]) == 1
