"""Number: the manual setpoint of the thermostat designated for the supervised trial.

The only write the Companion can publish, and not an open one: the entity exists for one
thermostat, chosen by the owner in the options, and only once its bridge has said it is not read
only (`CompanionCoordinator.supports_set`). It shows `current_heating_setpoint`, the setpoint of
the **manual** preset: in another preset the thermostat stores a new value and does not regulate
on it.

Nothing is assumed after a write: the value shown changes when the bridge publishes what the
device confirmed.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CompanionConfigEntry, CompanionData
from .const import SET_BOUNDS
from .entity import ThermostatEntity

SET_KEY = "current_heating_setpoint"
SUFFIX = "manual_setpoint"


class ManualSetpoint(ThermostatEntity, NumberEntity):
    """The manual-preset setpoint of the trial thermostat."""

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
    """Create the trial thermostat's setpoint once a write route exists for it."""
    data = entry.runtime_data
    coordinator = data.coordinator
    created = False

    @callback
    def discover() -> None:
        nonlocal created
        key = coordinator.trial_thermostat
        if created or key is None or not coordinator.supports_set(key, SET_KEY):
            return
        created = True
        async_add_entities([ManualSetpoint(data, key)])

    entry.async_on_unload(coordinator.async_add_listener(discover))
    discover()
