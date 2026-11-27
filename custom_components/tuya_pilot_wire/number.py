"""Number: the manual setpoint of one thermostat, in a room or not.

The entity exists for a thermostat once its bridge has announced the manual setpoint open for it
(`CompanionCoordinator.supports_set`), and is unavailable whenever the bridge closes it again. It
shows `current_heating_setpoint`, the setpoint of the **manual** preset; a write is refused
before anything is sent while the thermostat is in another preset, where the device does not keep
it (contract §4).

Nothing is assumed after a write: the value shown changes when the bridge publishes what the
device confirmed.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CompanionConfigEntry, CompanionData
from .const import SET_BOUNDS
from .entity import ThermostatEntity, split_unique_id

SET_KEY = "current_heating_setpoint"
SUFFIX = "manual_setpoint"


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
    """Create a thermostat's setpoint once its bridge opens the write, and those registered."""
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
