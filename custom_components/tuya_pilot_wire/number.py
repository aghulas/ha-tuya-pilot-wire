"""Numbers: the manual setpoint of one thermostat; the calibration and the holiday setpoint of
one thermostat and of a room.

The entity exists for a thermostat once its bridge has announced the manual setpoint open for it
(`CompanionCoordinator.supports_set`), and is unavailable whenever the bridge closes it again. It
shows `current_heating_setpoint`, the setpoint of the **manual** preset; a write is refused
before anything is sent while the thermostat is in another preset, where the device does not keep
it (contract §4).

The calibration (`local_temperature_calibration`, −9 to 9 by 1) and the holiday setpoint
(`holiday_temperature`, 5 to 30 °C by 0.5) follow the same opening rule, per thermostat, and per
room when open for every member; a room's value is the members' common one, unavailable when one
does not report it or when they disagree. Neither depends on the preset.

Nothing is assumed after a write: the value shown changes when the bridge publishes what the
device confirmed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CompanionConfigEntry, CompanionData
from .const import SET_BOUNDS
from .entity import (
    CompanionDescription,
    RoomSettingEntity,
    ThermostatEntity,
    ThermostatSettingEntity,
    async_setup_settings,
    split_unique_id,
)

SET_KEY = "current_heating_setpoint"
SUFFIX = "manual_setpoint"


@dataclass(frozen=True, kw_only=True)
class CompanionNumberDescription(CompanionDescription, NumberEntityDescription):
    """A setting number; its key is the `/set` key, its bounds those of `SET_BOUNDS`."""


def _bounded(key: str) -> dict[str, float]:
    low, high, step = SET_BOUNDS[key]
    return {"native_min_value": low, "native_max_value": high, "native_step": step}


SETTINGS: tuple[CompanionNumberDescription, ...] = (
    CompanionNumberDescription(
        key="local_temperature_calibration",
        translation_key="local_temperature_calibration",
        # A temperature difference: no temperature device class, which would convert it as a
        # temperature for a Fahrenheit install.
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        thermostat_fn=lambda t: t.local_temperature_calibration,
        room_fn=lambda r: r.local_temperature_calibration,
        **_bounded("local_temperature_calibration"),
    ),
    CompanionNumberDescription(
        key="holiday_temperature",
        translation_key="holiday_temperature",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        thermostat_fn=lambda t: t.holiday_temperature,
        room_fn=lambda r: r.holiday_temperature,
        **_bounded("holiday_temperature"),
    ),
)


class _SettingNumber(NumberEntity):
    """A number whose value is read and written as a setting."""

    entity_description: CompanionNumberDescription
    # From the thermostat or room setting entity.
    reported: Any
    async_write: Callable[[Any], Awaitable[None]]

    @property
    def native_value(self) -> float | None:
        return self.reported

    async def async_set_native_value(self, value: float) -> None:
        """WRITE. Checked against the bounds, then one command per thermostat."""
        await self.async_write(value)


class ThermostatSettingNumber(ThermostatSettingEntity, _SettingNumber):
    """A setting number of one thermostat."""


class RoomSettingNumber(RoomSettingEntity, _SettingNumber):
    """A setting number of a room."""


class ManualSetpoint(ThermostatEntity, NumberEntity):
    """The manual-preset setpoint of a thermostat."""

    _attr_translation_key = "manual_setpoint"
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value, _attr_native_max_value, _attr_native_step = SET_BOUNDS[SET_KEY]

    def __init__(self, data: CompanionData, key: str) -> None:
        super().__init__(data, key, SUFFIX)

    @property
    def native_value(self) -> float | None:
        thermostat = self.thermostat
        return thermostat.number(SET_KEY) if thermostat is not None else None

    @property
    def available(self) -> bool:
        return (
            self._data.coordinator.supports_set(self._key, SET_KEY)
            and self.native_value is not None
        )

    async def async_set_native_value(self, value: float) -> None:
        """WRITE. Send the setpoint to the bridge; the state follows the device's confirmation."""
        await self._data.coordinator.async_set(self._key, SET_KEY, value)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create each number once its bridge opens the write, and those registered."""
    data = entry.runtime_data
    coordinator = data.coordinator
    known: set[str] = set()

    def build(key: str) -> ManualSetpoint | None:
        if key in known:
            return None
        known.add(key)
        return ManualSetpoint(data, key)

    restored: list[ManualSetpoint] = []
    for registered in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if registered.domain != "number":
            continue
        parts = split_unique_id(registered.unique_id, (SUFFIX,))
        if parts and (entity := build(parts[0])) is not None:
            restored.append(entity)
    async_add_entities(restored)

    @callback
    def discover() -> None:
        new = [
            entity
            for key in coordinator.thermostats
            if coordinator.supports_set(key, SET_KEY) and (entity := build(key)) is not None
        ]
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(discover))
    discover()

    async_setup_settings(
        hass,
        entry,
        async_add_entities,
        "number",
        SETTINGS,
        ThermostatSettingNumber,
        RoomSettingNumber,
    )
