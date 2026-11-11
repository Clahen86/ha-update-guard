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
    # Breaking, but nothing in this system shows it is used: check first, not wait.
    assert state.state == "check"
    app = state.attributes["updates"][0]
    assert app["kind"] == "app" and app["level"] == "check"
    assert app["verdict"].startswith("Check first") and "not found in your system" in app["verdict"]
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


async def test_hacs_integration_option_changes(hass: HomeAssistant, aioclient_mock) -> None:
    from types import SimpleNamespace

    _mock_github(aioclient_mock)
    aioclient_mock.get("https://raw.githubusercontent.com/someone/solar/v5.0.0/hacs.json", json={})
    MockConfigEntry(domain="solar", data={"api_key": "secret"}, options={"damp_factor": 0.8}).add_to_hass(hass)
    repo = SimpleNamespace(data=SimpleNamespace(category="integration", domain="solar"))
    hass.data["hacs"] = SimpleNamespace(
        repositories=SimpleNamespace(get_by_id=lambda rid: repo if rid == "777" else None)
    )
    er.async_get(hass).async_get_or_create("update", "hacs", "777", suggested_object_id="solar_update")
    hass.states.async_set(
        "update.solar_update",
        "on",
        {
            "installed_version": "v4.0.0",
            "latest_version": "v5.0.0",
            "title": "Solar",
            "release_url": "https://github.com/someone/solar/releases/v5.0.0",
            "release_summary": "- `damp_factor` has been replaced by per-hour dampening\n- New sensors",
        },
    )
    await _setup(hass)
    update = hass.states.get("sensor.update_guard_assessment").attributes["updates"][0]
    assert update["kind"] == "hacs" and update["level"] == "wait"
    assert update["findings"][0]["source"] == "option" and update["findings"][0]["title"] == "damp_factor"
    assert "secret" not in str(update)  # only option names, never values


async def test_notifications(hass: HomeAssistant, aioclient_mock) -> None:
    from pytest_homeassistant_custom_component.common import async_mock_service

    _mock_github(aioclient_mock)
    calls = async_mock_service(hass, "notify", "mobile_app_phone")
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={"notify": ["notify.mobile_app_phone"], "notify_level": "safe"}
    )
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create("update", "esphome", "esp1", suggested_object_id="esphome_update")
    hass.states.async_set(
        "update.esphome_update",
        "on",
        {
            "installed_version": "2026.10.1",
            "latest_version": "2026.10.2",
            "title": "ESPHome",
            "release_summary": "- Keep TLS 1.3 working for audio streams\n- Fix the host build on macOS",
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data["title"] == "🟢 ESPHome 2026.10.2 – Safe"
    assert calls[0].data["data"]["url"] == "/config/repairs"

    # Same version again: no new message.
    await entry.runtime_data.async_refresh()
    assert len(calls) == 1

    # A new version with a breaking change is announced.
    hass.states.async_set(
        "update.esphome_update",
        "on",
        {
            "installed_version": "2026.10.1",
            "latest_version": "2026.11.0",
            "title": "ESPHome",
            "release_summary": "- BREAKING: `wifi.fast_connect` was removed",
        },
    )
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    assert len(calls) == 2
    assert calls[1].data["title"].startswith("🟡 ESPHome 2026.11.0")
    assert "wifi.fast_connect" in calls[1].data["message"]


async def test_notify_only_wait_and_combined(hass: HomeAssistant, aioclient_mock) -> None:
    from custom_components.update_guard.notifier import build_message

    title, message = build_message(
        [
            {"name": "A", "latest": "1", "level": "safe", "findings": []},
            {
                "name": "B",
                "latest": "2",
                "level": "wait",
                "findings": [
                    {"title": "x_y", "text": "removed", "general": False, "severe": True, "source": "changelog",
                     "affects": "yes", "used_in": ["automation: Lys"]}
                ],
            },
        ],
        "da",
    )
    assert title == "2 opdateringer: 🔴 1 · 🟢 1"
    assert message.splitlines()[0] == "🔴 B 2"
    assert "bruges i Lys" in message and "Vent" in message


async def test_options_flow(hass: HomeAssistant, aioclient_mock) -> None:
    from pytest_homeassistant_custom_component.common import async_mock_service

    _mock_github(aioclient_mock)
    async_mock_service(hass, "notify", "mobile_app_phone")
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    options = result["data_schema"].schema["notify"].config["options"]
    assert "notify.mobile_app_phone" in options
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"notify": ["notify.mobile_app_phone"], "notify_level": "check"}
    )
    await hass.async_block_till_done()
    assert entry.options["notify"] == ["notify.mobile_app_phone"] and entry.options["notify_level"] == "check"
    assert entry.options["wait_for_fix"] is False and entry.options["blockers"] == []


async def test_missing_notes_are_unknown_not_safe(hass: HomeAssistant, aioclient_mock) -> None:
    """No release notes, or notes that could not be fetched, must never look safe."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    # GitHub is down: the 2026.10 post can't be fetched.
    aioclient_mock.get(RELEASE, status=503)
    aioclient_mock.get(LATEST, status=503)
    calls = async_mock_service(hass, "notify", "mobile_app_phone")
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "update", "hassio", "home_assistant_core_version_latest", suggested_object_id="home_assistant_core_update"
    )
    hass.states.async_set(
        "update.home_assistant_core_update", "on", {"installed_version": "2026.9.3", "latest_version": "2026.10.4"}
    )
    registry.async_get_or_create("update", "esphome", "esp1", suggested_object_id="garage_firmware")
    hass.states.async_set(
        "update.garage_firmware",
        "on",
        {
            "installed_version": "1",
            "latest_version": "2",
            "title": "Garage",
            "release_url": "https://esphome.io/changelog",
        },
    )
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={"notify": ["notify.mobile_app_phone"], "notify_level": "check"}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.update_guard_assessment")
    assert state.state == "unclear"
    levels = {u["name"]: (u["level"], u["notes_missing"]) for u in state.attributes["updates"]}
    assert levels == {"Home Assistant Core": ("unclear", True), "Garage": ("unclear", True)}
    # "Only what needs a look" includes unknown.
    assert len(calls) == 1 and "⚪ 2" in calls[0].data["title"]


async def test_ai_check(hass: HomeAssistant, aioclient_mock) -> None:
    """The AI drops a false alarm, the answer is kept, and a broken AI falls back to the keyword verdict."""
    from homeassistant.core import SupportsResponse
    from homeassistant.exceptions import HomeAssistantError

    _mock_github(aioclient_mock)
    asked = []

    async def generate_data(call):
        asked.append(call.data)
        if call.data["entity_id"] == "ai_task.broken":
            raise HomeAssistantError("quota")
        return {
            "data": {
                "lines": [
                    {"n": 1, "relevant": False, "severe": False, "reason": "Kun for 32-bit"},
                    {"n": 2, "relevant": True, "severe": True, "reason": "Du bruger den"},
                ]
            }
        }

    hass.services.async_register("ai_task", "generate_data", generate_data, supports_response=SupportsResponse.ONLY)
    er.async_get(hass).async_get_or_create("update", "esphome", "esp1", suggested_object_id="esphome_update")
    hass.states.async_set(
        "update.esphome_update",
        "on",
        {
            "installed_version": "2026.10.1",
            "latest_version": "2026.11.0",
            "title": "ESPHome",
            "release_summary": "- Support for 32-bit platforms is deprecated\n"
            "- The `wifi.fast_connect` option is no longer supported",
        },
    )
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={"ai_task": "ai_task.gemini"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(asked) == 1
    prompt = asked[0]["instructions"]
    assert "1. Support for 32-bit" in prompt and "Danish" not in prompt
    update = hass.states.get("sensor.update_guard_assessment").attributes["updates"][0]
    # The AI can drop false alarms, but only proof from the system makes it wait.
    assert update["ai_checked"] and update["level"] == "check"
    first, second = update["findings"]
    assert "wifi.fast_connect" in first["text"] and first["ai"] == "Du bruger den" and not first["general"]
    assert second["general"] and second["ai"] == "Kun for 32-bit"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "risk_update.esphome_update")
    assert "🤖 Du bruger den" in issue.translation_placeholders["findings"]
    assert "32-bit" not in issue.translation_placeholders["findings"]

    # Same version: the answer is reused, no new call.
    await entry.runtime_data.async_refresh()
    assert len(asked) == 1

    # A broken AI: the keyword verdict stays, and it isn't asked again right away.
    hass.config_entries.async_update_entry(entry, options={"ai_task": "ai_task.broken"})
    await hass.async_block_till_done()
    entry.runtime_data.ai.answers.clear()
    await entry.runtime_data.async_refresh()
    await entry.runtime_data.async_refresh()
    assert len(asked) == 2
    update = entry.runtime_data.data["updates"][0]
    assert not update["ai_checked"] and update["level"] == "check"
    assert all(not f["ai"] for f in update["findings"])


async def test_after_update(hass: HomeAssistant, aioclient_mock) -> None:
    """What still doesn't work 5 and 30 minutes after an update is reported, and the repair goes away again."""
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

    from homeassistant.helpers import device_registry as dr
    from homeassistant.util import dt as dt_util

    from custom_components.update_guard import after

    _mock_github(aioclient_mock)
    calls = async_mock_service(hass, "notify", "mobile_app_phone")
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={"notify": ["notify.mobile_app_phone"], "notify_level": "check"}
    )
    entry.add_to_hass(hass)
    device_entry = MockConfigEntry(domain="esphome", title="Kitchen")
    device_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=device_entry.entry_id, identifiers={("esphome", "kitchen")}, name="Kitchen"
    )
    registry = er.async_get(hass)
    for object_id, platform, device_id in (
        ("kitchen_firmware", "esphome", device.id),
        ("kitchen_temp", "esphome", device.id),
        ("garage_temp", "demo", None),
        ("flaky", "demo", None),
    ):
        domain = "update" if object_id == "kitchen_firmware" else "sensor"
        registry.async_get_or_create(domain, platform, object_id, suggested_object_id=object_id, device_id=device_id)
    for entity_id in ("sensor.kitchen_temp", "sensor.garage_temp", "sensor.flaky"):
        hass.states.async_set(entity_id, "21")
    hass.states.async_set("update.kitchen_firmware", "off", {"installed_version": "1.0", "title": "Kitchen"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    checker = entry.runtime_data.after
    checker.baseline = after.snapshot(hass)

    # The firmware is installed, and three things go away.
    hass.states.async_set("update.kitchen_firmware", "off", {"installed_version": "2.0", "title": "Kitchen"})
    for entity_id in ("sensor.kitchen_temp", "sensor.garage_temp", "sensor.flaky"):
        hass.states.async_set(entity_id, "unavailable")
    await hass.async_block_till_done()
    assert checker.batch and checker.batch["updates"][0]["device"] == device.id
    # Home Assistant restarted after the update: what else stopped at the same time is told too.
    checker.started = checker.batch["since"] + 1

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=301))
    await hass.async_block_till_done()
    assert checker.batch["first"]["entities"] == ["sensor.flaky", "sensor.garage_temp", "sensor.kitchen_temp"]
    # One comes back by itself: not reported.
    hass.states.async_set("sensor.flaky", "21")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1801))
    await hass.async_block_till_done()

    assert checker.batch is None
    issues = [i for (d, i) in ir.async_get(hass).issues if d == DOMAIN and i.startswith("after_")]
    assert len(issues) == 1
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issues[0])
    assert issue.severity == ir.IssueSeverity.ERROR
    findings = issue.translation_placeholders["findings"]
    stopped, coincidence = findings.split("At the same time")
    assert "Kitchen" in stopped and "garage" not in stopped.lower()
    assert "garage" in coincidence.lower() and "flaky" not in findings
    assert len(calls) == 1 and calls[0].data["title"] == "🔴 After Kitchen 2.0: 2 stopped working"

    # Everything works again: the repair goes away.
    hass.states.async_set("sensor.kitchen_temp", "21")
    hass.states.async_set("sensor.garage_temp", "21")
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2500))
    await hass.async_block_till_done()
    assert not [i for (d, i) in ir.async_get(hass).issues if d == DOMAIN and i.startswith("after_")]


async def test_after_update_ignores_what_was_off(hass: HomeAssistant, aioclient_mock) -> None:
    """An integration whose device was already off, and unrelated things without a restart, are not reported."""
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from homeassistant.config_entries import ConfigEntryState
    from homeassistant.util import dt as dt_util

    from custom_components.update_guard import after

    _mock_github(aioclient_mock)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    glances = MockConfigEntry(domain="glances", title="PC", state=ConfigEntryState.LOADED)
    glances.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create("sensor", "glances", "pc_cpu", suggested_object_id="pc_cpu", config_entry=glances)
    registry.async_get_or_create("sensor", "zha", "bulb", suggested_object_id="bulb")
    registry.async_get_or_create("update", "hassio", "abc_app_version_latest", suggested_object_id="app")
    hass.states.async_set("sensor.pc_cpu", "unavailable")  # the PC is switched off
    hass.states.async_set("sensor.bulb", "on")
    hass.states.async_set("update.app", "off", {"installed_version": "1.0", "title": "App"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    checker = entry.runtime_data.after
    checker.baseline = after.snapshot(hass)
    assert glances.entry_id not in checker.baseline["loaded"]

    # The app is updated; the PC's integration fails and the bulb goes off at the wall at the same time.
    hass.states.async_set("update.app", "off", {"installed_version": "2.0", "title": "App"})
    hass.states.async_set("sensor.bulb", "unavailable")
    glances.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=301))
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1801))
    await hass.async_block_till_done()
    assert checker.batch is None
    assert not [i for (d, i) in ir.async_get(hass).issues if d == DOMAIN and i.startswith("after_")]


async def test_app_domains() -> None:
    from custom_components.update_guard.after import app_domains

    assert app_domains("45df7312_zigbee2mqtt") == {"mqtt"}
    assert app_domains("core_mosquitto") == {"mqtt"}
    assert app_domains("core_zwave_js") == {"zwave_js"}
    assert app_domains("a0d7b954_appdaemon") == {"appdaemon"}


async def test_after_core_update(hass: HomeAssistant, aioclient_mock, hass_storage) -> None:
    """Home Assistant starting on a new version is an installed update, compared with what worked before."""
    import time

    _mock_github(aioclient_mock)
    hass_storage["update_guard.after"] = {
        "version": 1,
        "key": "update_guard.after",
        "data": {"baseline": {"time": time.time() - 60, "ok": ["sensor.x"], "loaded": []}, "core": "2026.9.0"},
    }
    entry = await _setup(hass)
    batch = entry.runtime_data.after.batch
    assert batch["updates"][0]["kind"] == "core" and batch["updates"][0]["from"] == "2026.9.0"
    assert batch["before"]["ok"] == ["sensor.x"]
