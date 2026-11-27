"""Climate entities: one per room, and one per thermostat outside any room.

Controls appear only where a bridge has opened them (`CompanionCoordinator.supports_set`) for
**every** thermostat the entity stands for: the preset (`program` / `manual`, the raw names of
the mode sensor) and the target temperature, which is the manual setpoint. Otherwise the entity
declares no feature and a single HVAC mode, the one reported, and gives nothing to press.

A command goes to each thermostat in turn (`async_set_many`), each answered by its bridge; the
entity's state does not move until the bridge publishes what the devices confirmed. A setpoint is
refused before anything is sent while one thermostat is not in `manual`: in any other preset the
device does not keep it.

The target is also given as the `target_temperature` attribute (and by the "Setpoint" sensor),
for when no control is open: the setpoint of the current preset when a property holds it, and
nothing in `program`, whose target is in no data point.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CompanionConfigEntry, CompanionData
from .const import DOMAIN, SET_BOUNDS, SET_PRESETS
from .entity import ROOM_PREFIX, RoomEntity, ThermostatEntity, split_unique_id
from .model import Thermostat
from .rooms import RoomState

SUFFIX = "climate"
SETPOINT = "current_heating_setpoint"
PRESET = "preset"
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


class _CompanionClimate(ClimateEntity):
    """What the room and thermostat climates share: controls only where the bridge opened them."""

    _data: CompanionData  # set by the thermostat or room base entity
    _attr_name = None
    _attr_translation_key = "thermostat"
    _attr_min_temp, _attr_max_temp, _attr_target_temperature_step = SET_BOUNDS[SETPOINT]
    # Home Assistant 2026.11 renamed the unit and temperature members (`native_…`) and warns
    # about the former names; earlier versions know only those.
    if _NATIVE_NAMES:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS

    @property
    def _source(self) -> Thermostat | RoomState | None:
        """The thermostat or room read, or None when it is not usable."""
        raise NotImplementedError

    @property
    def _members(self) -> list[str]:
        """Keys of the thermostats a command goes to."""
        raise NotImplementedError

    def _open(self, set_key: str) -> bool:
        members = self._members
        coordinator = self._data.coordinator
        return bool(members) and all(coordinator.supports_set(key, set_key) for key in members)

    @property
    def supported_features(self) -> ClimateEntityFeature:
        features = ClimateEntityFeature(0)
        if self._open(PRESET):
            features |= ClimateEntityFeature.PRESET_MODE
        if self._open(SETPOINT):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return features

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

    @property
    def preset_modes(self) -> list[str] | None:
        return list(SET_PRESETS) if self._open(PRESET) else None

    @property
    def preset_mode(self) -> str | None:
        """The members' common preset, when it is one that can be chosen here."""
        if not self._open(PRESET):
            return None
        preset = self._read("preset")
        return preset if preset in SET_PRESETS else None

    def _local_temperature(self) -> float | None:
        return self._read("local_temperature")

    def _target_temperature(self) -> float | None:
        return self._read("target_temperature") if self._open(SETPOINT) else None

    if _NATIVE_NAMES:
        native_current_temperature = property(_local_temperature)
        native_target_temperature = property(_target_temperature)
    else:
        current_temperature = property(_local_temperature)
        target_temperature = property(_target_temperature)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Refuse: on / off is not opened in this version."""
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_write_route")

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """WRITE. The preset, to every member; the state follows the devices' confirmation."""
        await self._data.coordinator.async_set_many(self._members, PRESET, preset_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """WRITE. The manual setpoint, to every member, all of which must be in `manual`."""
        if kwargs.get(ATTR_TEMPERATURE) is None or any(
            kwargs.get(name) is not None
            for name in (ATTR_HVAC_MODE, ATTR_TARGET_TEMP_LOW, ATTR_TARGET_TEMP_HIGH)
        ):
            # A range or an HVAC mode with the temperature: no route for either.
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_write_route"
            )
        await self._data.coordinator.async_set_many(
            self._members, SETPOINT, float(kwargs[ATTR_TEMPERATURE])
        )


class ThermostatClimate(ThermostatEntity, _CompanionClimate):
    """The climate of a thermostat that belongs to no room."""

    def __init__(self, data: CompanionData, key: str) -> None:
        super().__init__(data, key, SUFFIX)

    @property
    def _source(self) -> Thermostat | None:
        return self.thermostat

    @property
    def _members(self) -> list[str]:
        return [self._key]

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


class RoomClimate(RoomEntity, _CompanionClimate):
    """The climate of a room."""

    def __init__(self, data: CompanionData, room_id: str) -> None:
        super().__init__(data, room_id, SUFFIX)

    @property
    def _source(self) -> RoomState | None:
        return self.room_state

    @property
    def _members(self) -> list[str]:
        room = self._data.store.rooms.get(self._room_id)
        return list(room.members) if room is not None else []

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
