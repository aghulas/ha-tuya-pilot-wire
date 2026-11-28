"""Rooms: the grouping Tuya does not have, kept by the Companion in Home Assistant storage.

A room is a name and a list of thermostats; a thermostat belongs to one room at most. The room's
values are computed from its members on demand (`RoomState`) and follow one rule: a room value is
given only when it is true of the room.

- temperature: mean of the members that report one;
- on / off, preset, target, and the settings a bridge can open (child lock, window detection,
  calibration, holiday setpoint): the members' common value; nothing when one member's value is
  unknown; nothing when they disagree, and the disagreement is named (for a setting, while the
  room's control of it is open: otherwise nothing of the room depends on it);
- heating, window, fault: true as soon as one member says so, false only when every member says
  not;
- power, energy: sums, given only when **every** member reports the figure. A partial sum would
  read as a drop, which an energy counter must never show.

The store also remembers which IEEE address goes with which Tuya device id, so that a thermostat
re-paired from the Tuya gateway to a Zigbee coordinator keeps its identity (milestone M5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .model import Thermostat

if TYPE_CHECKING:
    from .coordinator import CompanionCoordinator

COMPARED = ("system_mode", "preset", "target_temperature")
# The settings with a room control (`switch`, `number`); each name is also its `/set` key.
SETTINGS = (
    "child_lock",
    "window_detection",
    "local_temperature_calibration",
    "holiday_temperature",
)


class RoomError(HomeAssistantError):
    """A room operation was refused. ``code`` is a translation key."""

    def __init__(self, code: str, **placeholders: str) -> None:
        super().__init__(code)
        self.code = code
        self.placeholders = placeholders


@dataclass
class Room:
    """A room as stored."""

    id: str
    name: str
    members: list[str] = field(default_factory=list)


class CompanionStore:
    """Rooms and thermostat identities, persisted."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.rooms: dict[str, Room] = {}
        self.identities: dict[str, str] = {}  # IEEE address -> thermostat key
        self.aliases: dict[str, str] = {}  # later Tuya device id -> thermostat key

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.rooms = {
            room["id"]: Room(room["id"], room["name"], list(room["members"]))
            for room in data.get("rooms", [])
        }
        self.identities = dict(data.get("identities", {}))
        self.aliases = dict(data.get("aliases", {}))

    def _save(self) -> None:
        self._store.async_delay_save(self._data, 1)

    def _data(self) -> dict[str, Any]:
        return {
            "rooms": [
                {"id": room.id, "name": room.name, "members": list(room.members)}
                for room in self.rooms.values()
            ],
            "identities": dict(self.identities),
            "aliases": dict(self.aliases),
        }

    async def async_flush(self) -> None:
        """Write pending changes now."""
        await self._store.async_save(self._data())

    # -- identities --------------------------------------------------------------------------

    def resolve_key(self, dev_id: str | None, ieee: str | None) -> str | None:
        """Stable key of a thermostat described with a Tuya device id and / or an IEEE address.

        The key is the first Tuya device id the thermostat was seen with, and it never changes
        (unique ids hang on it):

        - an IEEE address seen once with a device id keeps pointing at that key when it later
          comes alone, from Zigbee2MQTT;
        - a thermostat re-paired to its Tuya gateway gets a **new** device id but keeps its IEEE
          address (the hardware's): the known address wins, and the new device id is remembered
          as an alias of the key, for a later listing that gives the device id alone.

        With neither seen before, the device id is the key, else the IEEE address.
        """
        known = self.identities.get(ieee) if ieee else None
        if known is not None:
            if dev_id and dev_id != known and self.aliases.get(dev_id) != known:
                self.aliases[dev_id] = known
                self._save()
            return known
        if dev_id:
            key = self.aliases.get(dev_id, dev_id)
            if ieee:
                self.identities[ieee] = key
                self._save()
            return key
        return ieee or None

    # -- rooms -------------------------------------------------------------------------------

    def room_of(self, key: str) -> Room | None:
        """The room a thermostat belongs to, or None."""
        for room in self.rooms.values():
            if key in room.members:
                return room
        return None

    def _check(self, name: str, members: list[str], room_id: str | None) -> tuple[str, list[str]]:
        name = name.strip()
        if not name:
            raise RoomError("room_name_empty")
        for other in self.rooms.values():
            if other.id != room_id and other.name.casefold() == name.casefold():
                raise RoomError("room_name_taken", name=name)
        members = list(dict.fromkeys(members))
        for key in members:
            owner = self.room_of(key)
            if owner is not None and owner.id != room_id:
                raise RoomError("thermostat_in_other_room", room=owner.name)
        return name, members

    def create(self, name: str, members: list[str]) -> Room:
        """Create a room. Raises ``RoomError``."""
        name, members = self._check(name, members, None)
        room = Room(uuid.uuid4().hex[:12], name, members)
        self.rooms[room.id] = room
        self._save()
        return room

    def update(
        self, room_id: str, name: str | None = None, members: list[str] | None = None
    ) -> Room:
        """Rename a room and / or replace its members. Raises ``RoomError``."""
        room = self.rooms[room_id]
        new_name, new_members = self._check(
            room.name if name is None else name,
            room.members if members is None else members,
            room_id,
        )
        room.name, room.members = new_name, new_members
        self._save()
        return room

    def delete(self, room_id: str) -> None:
        """Delete a room; its thermostats become thermostats outside any room."""
        del self.rooms[room_id]
        self._save()


def _common(values: list[Any]) -> tuple[Any, bool]:
    """``(value, agreed)`` over the members' values, an unknown value being ``None``.

    Two known values that differ are a disagreement. A member whose value is unknown is not: the
    room's value is then unknown, and nobody is said to disagree.
    """
    known = [value for value in values if value is not None]
    if any(value != known[0] for value in known[1:]):
        return None, False
    if len(known) != len(values) or not known:
        return None, True
    return known[0], True


def _any(values: list[bool | None], complete: bool) -> bool | None:
    """True if one says so; False if all say not and none is missing; else unknown."""
    if any(value is True for value in values):
        return True
    if complete and values and all(value is False for value in values):
        return False
    return None


class RoomState:
    """Values of a room, computed from its members as they are now."""

    def __init__(self, room: Room, coordinator: CompanionCoordinator) -> None:
        self.room = room
        self._coordinator = coordinator
        self.members: list[Thermostat] = [
            thermostat for key in room.members if (thermostat := coordinator.get(key)) is not None
        ]
        # Every stored member is there and usable.
        self.complete = bool(room.members) and len(self.members) == len(room.members)

    @property
    def available(self) -> bool:
        return bool(self.members)

    @property
    def missing(self) -> int:
        """Number of members that are not usable right now."""
        return len(self.room.members) - len(self.members)

    def _agreed(self, name: str) -> tuple[Any, bool]:
        return _common([getattr(member, name) for member in self.members])

    @property
    def local_temperature(self) -> float | None:
        values = [
            value for member in self.members if (value := member.local_temperature) is not None
        ]
        return round(sum(values) / len(values), 2) if values else None

    @property
    def system_mode(self) -> str | None:
        return self._agreed("system_mode")[0]

    @property
    def preset(self) -> str | None:
        return self._agreed("preset")[0]

    @property
    def target_temperature(self) -> float | None:
        return self._agreed("target_temperature")[0]

    @property
    def child_lock(self) -> bool | None:
        return self._agreed("child_lock")[0]

    @property
    def window_detection(self) -> bool | None:
        return self._agreed("window_detection")[0]

    @property
    def local_temperature_calibration(self) -> float | None:
        return self._agreed("local_temperature_calibration")[0]

    @property
    def holiday_temperature(self) -> float | None:
        return self._agreed("holiday_temperature")[0]

    def setting_open(self, set_key: str) -> bool:
        """True when every stored member's bridge opens ``set_key`` for it."""
        return bool(self.room.members) and all(
            self._coordinator.supports_set(key, set_key) for key in self.room.members
        )

    @property
    def disagreements(self) -> list[str]:
        """Names of the values the members do not share.

        A setting is named only while the room's control of it is open: it is then the reason
        that control is unavailable.
        """
        names = [name for name in COMPARED if not self._agreed(name)[1]]
        names += [
            name for name in SETTINGS if not self._agreed(name)[1] and self.setting_open(name)
        ]
        return names

    @property
    def heating(self) -> bool | None:
        return _any([member.heating for member in self.members], self.complete)

    @property
    def window_open(self) -> bool | None:
        return _any([member.window_open for member in self.members], self.complete)

    @property
    def fault(self) -> bool | None:
        return _any([member.fault for member in self.members], self.complete)

    @property
    def faults(self) -> list[str] | None:
        """Fault names over the members that report them, without duplicates."""
        lists = [faults for member in self.members if (faults := member.faults) is not None]
        return sorted({name for faults in lists for name in faults}) if lists else None

    def number(self, name: str) -> float | None:
        """Sum of a figure over the room, or None unless every member reports it."""
        if not self.complete:
            return None
        values = [member.number(name) for member in self.members]
        if any(value is None for value in values):
            return None
        return round(sum(value for value in values if value is not None), 3)
