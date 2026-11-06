"""Sensors: overall assessment and number of things to check."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LEVELS
from .coordinator import UpdateGuardConfigEntry
from .entity import UpdateGuardEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: UpdateGuardConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([AssessmentSensor(coordinator, "assessment"), FindingsSensor(coordinator, "findings")])


class AssessmentSensor(UpdateGuardEntity, SensorEntity):
    """safe / check / wait / none, with the details as attributes."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = LEVELS
    # The details can be long and change rarely; keep them out of the database.
    _unrecorded_attributes = frozenset({"updates", "dead", "planned", "disk_free"})

    @property
    def native_value(self) -> str:
        return self.coordinator.data["level"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "updates": data["updates"],
            "checked": data["checked"],
            "dead": data.get("dead", []),
            "planned": data.get("planned", []),
            "disk_free": data.get("disk_free"),
        }


class FindingsSensor(UpdateGuardEntity, SensorEntity):
    """How many things to look at before updating."""

    @property
    def native_value(self) -> int:
        return self.coordinator.data["findings"]
