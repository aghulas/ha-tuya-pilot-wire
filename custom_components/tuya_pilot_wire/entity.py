"""Base entities: one for a thermostat, one for a room, and the discovery both platforms share.

An entity is created the first time its value exists (a bridge published the property), or
because it is already in the entity registry; it is unavailable whenever its value is unknown.
Nothing is created on the assumption that a bridge will publish it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, MANUFACTURER, ROOM_MODEL
from .model import Thermostat
from .rooms import RoomState

if TYPE_CHECKING:
    from . import CompanionConfigEntry, CompanionData

ROOM_PREFIX = "room_"


def room_identifier(room_id: str) -> str:
    """Device identifier and unique-id stem of a room."""
    return f"{ROOM_PREFIX}{room_id}"


@dataclass(frozen=True, kw_only=True)
class CompanionDescription(EntityDescription):
    """An entity kind: how to read it on a thermostat and, where it has a meaning, on a room."""

    thermostat_fn: Callable[[Thermostat], Any] | None = None
    room_fn: Callable[[RoomState], Any] | None = None


class CompanionEntity(Entity):
    """Common ground: pushed, named after its device, refreshed on every fleet change."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, data: CompanionData) -> None:
        self._data = data

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._data.coordinator.async_add_listener(self.async_write_ha_state))


class ThermostatEntity(CompanionEntity):
    """An entity of one thermostat."""

    def __init__(self, data: CompanionData, key: str, suffix: str) -> None:
        super().__init__(data)
        self._key = key
        self._attr_unique_id = f"{key}_{suffix}"
        info = DeviceInfo(identifiers={(DOMAIN, key)})
        thermostat = data.coordinator.thermostats.get(key)
        if thermostat is not None:
            info["name"] = thermostat.friendly_name
            info["manufacturer"] = thermostat.vendor or MANUFACTURER
            info["model"] = thermostat.model
        self._attr_device_info = info

    @property
    def thermostat(self) -> Thermostat | None:
        """The thermostat while it is usable, else None."""
        return self._data.coordinator.get(self._key)


class RoomEntity(CompanionEntity):
    """An entity of one room."""

    def __init__(self, data: CompanionData, room_id: str, suffix: str) -> None:
        super().__init__(data)
        self._room_id = room_id
        self._attr_unique_id = f"{room_identifier(room_id)}_{suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, room_identifier(room_id))},
            name=data.store.rooms[room_id].name,
            manufacturer="Tuya Pilot Wire Companion",
            model=ROOM_MODEL,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def room_state(self) -> RoomState | None:
        """The room's values, or None when the room is gone or has no usable member."""
        room = self._data.store.rooms.get(self._room_id)
        if room is None:
            return None
        state = RoomState(room, self._data.coordinator)
        return state if state.available else None


class DescribedThermostatEntity(ThermostatEntity):
    """A thermostat entity whose value is read by its description."""

    entity_description: CompanionDescription

    def __init__(self, data: CompanionData, key: str, description: CompanionDescription) -> None:
        super().__init__(data, key, description.key)
        self.entity_description = description

    @property
    def value(self) -> Any:
        thermostat = self.thermostat
        fn = self.entity_description.thermostat_fn
        return fn(thermostat) if thermostat is not None and fn is not None else None

    @property
    def available(self) -> bool:
        return self.value is not None


class DescribedRoomEntity(RoomEntity):
    """A room entity whose value is read by its description."""

    entity_description: CompanionDescription

    def __init__(
        self, data: CompanionData, room_id: str, description: CompanionDescription
    ) -> None:
        super().__init__(data, room_id, description.key)
        self.entity_description = description

    @property
    def value(self) -> Any:
        state = self.room_state
        fn = self.entity_description.room_fn
        return fn(state) if state is not None and fn is not None else None

    @property
    def available(self) -> bool:
        return self.value is not None


def split_unique_id(unique_id: str, suffixes: Iterable[str]) -> tuple[str, str] | None:
    """``(owner, suffix)`` of one of our unique ids, the longest suffix winning; None if foreign."""
    for suffix in sorted(suffixes, key=len, reverse=True):
        if unique_id.endswith(f"_{suffix}"):
            return unique_id[: -len(suffix) - 1], suffix
    return None


@callback
def async_setup_described(
    hass: HomeAssistant,
    entry: CompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    domain: str,
    descriptions: tuple[CompanionDescription, ...],
    thermostat_cls: Callable[[CompanionData, str, Any], Entity],
    room_cls: Callable[[CompanionData, str, Any], Entity],
) -> None:
    """Create a platform's entities as their values appear, and those the registry already has."""
    data = entry.runtime_data
    by_key = {description.key: description for description in descriptions}
    known: set[str] = set()

    def build(owner: str, description: CompanionDescription) -> Entity | None:
        unique_id = f"{owner}_{description.key}"
        if unique_id in known:
            return None
        if owner.startswith(ROOM_PREFIX):
            room_id = owner.removeprefix(ROOM_PREFIX)
            if description.room_fn is None or room_id not in data.store.rooms:
                return None
            known.add(unique_id)
            return room_cls(data, room_id, description)
        if description.thermostat_fn is None:
            return None
        known.add(unique_id)
        return thermostat_cls(data, owner, description)

    # What a previous run created exists again at once, unavailable until its value comes back.
    restored: list[Entity] = []
    for registered in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if registered.domain != domain:
            continue
        parts = split_unique_id(registered.unique_id, by_key)
        if parts and (entity := build(parts[0], by_key[parts[1]])) is not None:
            restored.append(entity)
    async_add_entities(restored)

    @callback
    def discover() -> None:
        new: list[Entity] = []
        for key, thermostat in data.coordinator.thermostats.items():
            for description in descriptions:
                fn = description.thermostat_fn
                if (
                    fn is not None
                    and fn(thermostat) is not None
                    and (entity := build(key, description)) is not None
                ):
                    new.append(entity)
        for room in data.store.rooms.values():
            state = RoomState(room, data.coordinator)
            for description in descriptions:
                fn_room = description.room_fn
                if (
                    fn_room is not None
                    and fn_room(state) is not None
                    and (entity := build(room_identifier(room.id), description)) is not None
                ):
                    new.append(entity)
        if new:
            async_add_entities(new)

    entry.async_on_unload(data.coordinator.async_add_listener(discover))
    discover()
