"""Sensors per thermostat and per room: temperature, setpoint, power, energy and mode; and per
thermostat, voltage and current.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import CompanionConfigEntry
from .entity import (
    CompanionDescription,
    DescribedRoomEntity,
    DescribedThermostatEntity,
    async_setup_described,
)
from .model import PRESETS


@dataclass(frozen=True, kw_only=True)
class CompanionSensorDescription(CompanionDescription, SensorEntityDescription):
    """A sensor kind."""


SENSORS: tuple[CompanionSensorDescription, ...] = (
    CompanionSensorDescription(
        key="local_temperature",
        translation_key="local_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        thermostat_fn=lambda t: t.local_temperature,
        room_fn=lambda r: r.local_temperature,
    ),
    CompanionSensorDescription(
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        thermostat_fn=lambda t: t.target_temperature,
        room_fn=lambda r: r.target_temperature,
    ),
    CompanionSensorDescription(
        key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
        thermostat_fn=lambda t: t.number("power"),
        room_fn=lambda r: r.number("power"),
    ),
    CompanionSensorDescription(
        key="energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        thermostat_fn=lambda t: t.number("energy"),
        room_fn=lambda r: r.number("energy"),
    ),
    CompanionSensorDescription(
        key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=0,
        thermostat_fn=lambda t: t.number("voltage"),
    ),
    CompanionSensorDescription(
        key="current",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        thermostat_fn=lambda t: t.number("current"),
    ),
    CompanionSensorDescription(
        key="preset",
        translation_key="preset",
        device_class=SensorDeviceClass.ENUM,
        options=list(PRESETS),
        thermostat_fn=lambda t: t.preset,
        room_fn=lambda r: r.preset,
    ),
)


class ThermostatSensor(DescribedThermostatEntity, SensorEntity):
    """A sensor of one thermostat."""

    entity_description: CompanionSensorDescription

    @property
    def native_value(self) -> StateType:
        return self.value


class RoomSensor(DescribedRoomEntity, SensorEntity):
    """A sensor of one room."""

    entity_description: CompanionSensorDescription

    @property
    def native_value(self) -> StateType:
        return self.value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_setup_described(
        hass, entry, async_add_entities, "sensor", SENSORS, ThermostatSensor, RoomSensor
    )
