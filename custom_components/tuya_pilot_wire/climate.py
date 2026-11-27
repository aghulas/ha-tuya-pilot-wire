"""Climate entities: one per room, and one per thermostat outside any room. Read only.

No write route is open in the Companion yet, so these entities declare **no feature** and offer a
single HVAC mode, the one the device reports: the interface shows a thermostat and gives nothing
to press. A service call that tries anyway is refused with an explicit message. Milestone M4
turns the features on one at a time.

Home Assistant shows a climate's target only together with the control that sets it, so the
target is given here as the `target_temperature` attribute (and by the "Setpoint" sensor). It is
the setpoint the thermostat regulates on: that of its current preset when a property holds it,
and nothing in `program`, whose target is in no data point.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CompanionConfigEntry, CompanionData
from .const import DOMAIN
from .entity import ROOM_PREFIX, RoomEntity, ThermostatEntity, split_unique_id
from .model import Thermostat
from .rooms import RoomState

SUFFIX = "climate"
_SETPOINTS = (
    "current_heating_setpoint",
    "eco_temperature",
    "antifrost_temperature",
    "holiday_temperature",
)


_NATIVE_NAMES = hasattr(ClimateEntity, "native_current_temperature")


def _hvac_mode(system_mode: str | None) -> HVACMode | None:
    if system_mode == "heat":
        return HVACMode.HEAT
    if system_mode == "off":
        return HVACMode.OFF
    return None


def _hvac_action(mode: HVACMode | None, heating: bool | None) -> HVACAction | None:
    if mode is HVACMode.OFF:
        return HVACAction.OFF
    if heating is None:
        return None
    return HVACAction.HEATING if heating else HVACAction.IDLE


class _ReadOnlyClimate(ClimateEntity):
    """What the room and thermostat climates share: no feature, no command."""

    _attr_name = None
    _attr_translation_key = "thermostat"
    _attr_supported_features = ClimateEntityFeature(0)
    # Home Assistant 2026.11 renamed the unit and current-temperature members (`native_…`) and
    # warns about the former names; earlier versions know only those.
    if _NATIVE_NAMES:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS

    @property
    def _source(self) -> Thermostat | RoomState | None:
        """The thermostat or room read, or None when it is not usable."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        return self._source is not None

    def _read(self, name: str) -> Any:
        source = self._source
        return getattr(source, name) if source is not None else None

    @property
    def hvac_mode(self) -> HVACMode | None:
        return _hvac_mode(self._read("system_mode"))

    @property
    def hvac_modes(self) -> list[HVACMode]:
        mode = self.hvac_mode
        return [mode] if mode is not None else []

    @property
    def hvac_action(self) -> HVACAction | None:
        return _hvac_action(self.hvac_mode, self._read("heating"))

    def _local_temperature(self) -> float | None:
        return self._read("local_temperature")

    if _NATIVE_NAMES:
        native_current_temperature = property(_local_temperature)
    else:
        current_temperature = property(_local_temperature)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Refuse: no write route is open."""
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_write_route")


class ThermostatClimate(ThermostatEntity, _ReadOnlyClimate):
    """The climate of a thermostat that belongs to no room."""

    def __init__(self, data: CompanionData, key: str) -> None:
        super().__init__(data, key, SUFFIX)

    @property
    def _source(self) -> Thermostat | None:
        return self.thermostat

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        thermostat = self.thermostat
        if thermostat is None:
            return None
        setpoints = {
            name: value for name in _SETPOINTS if (value := thermostat.number(name)) is not None
        }
        return {
            "preset": thermostat.preset,
            "target_temperature": thermostat.target_temperature,
            **setpoints,
        }


class RoomClimate(RoomEntity, _ReadOnlyClimate):
    """The climate of a room."""

    def __init__(self, data: CompanionData, room_id: str) -> None:
        super().__init__(data, room_id, SUFFIX)

    @property
    def _source(self) -> RoomState | None:
        return self.room_state

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        state = self.room_state
        if state is None:
            return None
        return {
            "preset": state.preset,
            "target_temperature": state.target_temperature,
            "members": [member.friendly_name for member in state.members],
            "members_missing": state.missing,
            "differing": state.disagreements,
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one climate per room and one per thermostat outside any room."""
    data = entry.runtime_data
    known: set[str] = set()

    def thermostat_climate(key: str) -> ThermostatClimate | None:
        if key in known or data.store.room_of(key) is not None:
            return None
        known.add(key)
        return ThermostatClimate(data, key)

    entities: list[ClimateEntity] = [RoomClimate(data, room_id) for room_id in data.store.rooms]
    for registered in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if registered.domain != "climate":
            continue
        parts = split_unique_id(registered.unique_id, (SUFFIX,))
        if (
            parts
            and not parts[0].startswith(ROOM_PREFIX)
            and (entity := thermostat_climate(parts[0])) is not None
        ):
            entities.append(entity)
    async_add_entities(entities)

    @callback
    def discover() -> None:
        new = [
            entity
            for key in data.coordinator.thermostats
            if (entity := thermostat_climate(key)) is not None
        ]
        if new:
            async_add_entities(new)

    entry.async_on_unload(data.coordinator.async_add_listener(discover))
    discover()
