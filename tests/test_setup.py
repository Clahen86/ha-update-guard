"""The setup for the developer: kinds of updates by integration and what was installed - no names or entity IDs."""

from pytest_homeassistant_custom_component.common import async_mock_service

from homeassistant.core import HomeAssistant

from custom_components.update_guard.setup import setup_info

from .test_features import _card_releases, _setup, _store_update
from .test_init import _mock_github


async def test_setup_info(hass: HomeAssistant, aioclient_mock) -> None:
    _card_releases(aioclient_mock)
    _mock_github(aioclient_mock)
    await _store_update(hass)
    entry = await _setup(hass, {"ai_task": "ai_task.x"})
    async_mock_service(hass, "update", "install")
    coordinator = entry.runtime_data
    await coordinator.installer.async_safe_update("update.cool_card_update", force=True)
    su = setup_info(coordinator)
    g = next(d for d in su["devices"] if d["platform"] == "marketplace")
    assert g["kind"] == "update" and g["extra"]["watched"] == 1 and g["extra"]["pending"] == 1
    assert su["counts"]["installed"] == 1 and su["counts"]["watched"] == 1
    assert su["features"]["ai"] is True
    assert "cool_card" not in str(su) and "Cool card" not in str(su)
