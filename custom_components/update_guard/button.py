"""Button to check again right away."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import UpdateGuardConfigEntry
from .entity import UpdateGuardEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: UpdateGuardConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([CheckButton(entry.runtime_data, "check_now")])


class CheckButton(UpdateGuardEntity, ButtonEntity):
    async def async_press(self) -> None:
        await self.coordinator.async_refresh()
