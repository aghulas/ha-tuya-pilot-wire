"""Binary sensors: heating, window and fault per thermostat and per room; disagreement per room."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CompanionConfigEntry
from .entity import (
    CompanionDescription,
    DescribedRoomEntity,
    DescribedThermostatEntity,
    async_setup_described,
)


@dataclass(frozen=True, kw_only=True)
class CompanionBinaryDescription(CompanionDescription, BinarySensorEntityDescription):
    """A binary sensor kind."""


BINARY_SENSORS: tuple[CompanionBinaryDescription, ...] = (
    CompanionBinaryDescription(
        key="heating",
        translation_key="heating",
        device_class=BinarySensorDeviceClass.HEAT,
        thermostat_fn=lambda t: t.heating,
        room_fn=lambda r: r.heating,
    ),
    CompanionBinaryDescription(
        key="window",
        device_class=BinarySensorDeviceClass.WINDOW,
        thermostat_fn=lambda t: t.window_open,
        room_fn=lambda r: r.window_open,
    ),
    CompanionBinaryDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        thermostat_fn=lambda t: t.fault,
        room_fn=lambda r: r.fault,
    ),
    CompanionBinaryDescription(
        key="disagreement",
        translation_key="disagreement",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        room_fn=lambda r: bool(r.disagreements),
    ),
)


class ThermostatBinarySensor(DescribedThermostatEntity, BinarySensorEntity):
    """A binary sensor of one thermostat."""

    entity_description: CompanionBinaryDescription

    @property
    def is_on(self) -> bool | None:
        return self.value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        thermostat = self.thermostat
        if self.entity_description.key == "fault" and thermostat is not None:
            return {"faults": thermostat.faults}
        return None


class RoomBinarySensor(DescribedRoomEntity, BinarySensorEntity):
    """A binary sensor of one room."""

    entity_description: CompanionBinaryDescription

    @property
    def is_on(self) -> bool | None:
        return self.value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        state = self.room_state
        if state is None:
            return None
        if self.entity_description.key == "fault":
            return {"faults": state.faults}
        if self.entity_description.key == "disagreement":
            return {"differing": state.disagreements, "members_missing": state.missing}
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    async_setup_described(
        hass,
        entry,
        async_add_entities,
        "binary_sensor",
        BINARY_SENSORS,
        ThermostatBinarySensor,
        RoomBinarySensor,
    )
