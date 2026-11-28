"""Services: the rooms the Companion keeps, and the weekly schedule.

The room services (create, update, delete, list) change Home Assistant storage only; nothing is
sent to a bridge or a thermostat. After a change the entry reloads, because the set of entities
follows the rooms.

`get_schedule` gives the schedule of a room or a thermostat as last read by the bridge, or asks
the bridge to read it now (`refresh`). `set_schedule` WRITES the given days to a room's members
or a thermostat, one after the other, each confirmed by its bridge (contract §5).

A room is named by its Home Assistant device id, its room id or its name; a thermostat by its
Home Assistant device id, its key or its bridge name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from . import schedule
from .const import (
    ATTR_DAYS,
    ATTR_NAME,
    ATTR_REFRESH,
    ATTR_ROOM,
    ATTR_SCHEDULE,
    ATTR_THERMOSTAT,
    ATTR_THERMOSTATS,
    ATTR_TRANSITIONS,
    DOMAIN,
    SERVICE_CREATE_ROOM,
    SERVICE_DELETE_ROOM,
    SERVICE_GET_SCHEDULE,
    SERVICE_LIST_ROOMS,
    SERVICE_SET_SCHEDULE,
    SERVICE_UPDATE_ROOM,
)
from .entity import ROOM_PREFIX
from .rooms import Room, RoomError

if TYPE_CHECKING:
    from . import CompanionConfigEntry, CompanionData

_THERMOSTATS = vol.All(cv.ensure_list, [cv.string])


def _refuse(code: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=code, translation_placeholders=placeholders
    )


def _loaded_entry(hass: HomeAssistant) -> CompanionConfigEntry:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    raise _refuse("not_loaded")


def _device_identifier(hass: HomeAssistant, reference: str) -> str | None:
    """Our identifier of a Home Assistant device id, or None when it is not one of ours."""
    device = dr.async_get(hass).async_get(reference)
    if device is not None:
        for domain, identifier in device.identifiers:
            if domain == DOMAIN:
                return identifier
    return None


def resolve_thermostat(hass: HomeAssistant, data: CompanionData, reference: str) -> str:
    """Key of the thermostat a service call names. Raises ``ServiceValidationError``."""
    thermostats = data.coordinator.thermostats
    identifier = _device_identifier(hass, reference) or reference
    if identifier in thermostats:
        return identifier
    named = [
        key
        for key, thermostat in thermostats.items()
        if thermostat.friendly_name.casefold() == reference.casefold()
    ]
    if len(named) == 1:
        return named[0]
    raise _refuse("thermostat_unknown", thermostat=reference)


def resolve_room(hass: HomeAssistant, data: CompanionData, reference: str) -> Room:
    """The room a service call names. Raises ``ServiceValidationError``."""
    rooms = data.store.rooms
    identifier = _device_identifier(hass, reference) or reference
    room = rooms.get(identifier.removeprefix(ROOM_PREFIX))
    if room is not None:
        return room
    for candidate in rooms.values():
        if candidate.name.casefold() == reference.strip().casefold():
            return candidate
    raise _refuse("room_unknown", room=reference)


def describe_room(data: CompanionData, room: Room) -> dict[str, Any]:
    """A room for a service response: its id, name and members by bridge name."""
    thermostats = data.coordinator.thermostats
    return {
        "id": room.id,
        "name": room.name,
        "thermostats": [
            thermostats[key].friendly_name if key in thermostats else key for key in room.members
        ],
    }


def _target(hass: HomeAssistant, data: CompanionData, call: ServiceCall) -> tuple[str, list[str]]:
    """``(label, thermostat keys)`` of the room or the thermostat a schedule service names."""
    if (ATTR_ROOM in call.data) == (ATTR_THERMOSTAT in call.data):
        raise _refuse("schedule_target")
    if ATTR_ROOM in call.data:
        room = resolve_room(hass, data, call.data[ATTR_ROOM])
        if not room.members:
            raise _refuse("room_empty", room=room.name)
        return room.name, list(room.members)
    key = resolve_thermostat(hass, data, call.data[ATTR_THERMOSTAT])
    return data.coordinator.name_of(key), [key]


def _days_asked(call: ServiceCall) -> dict[str, Any]:
    """The days to write: ``schedule`` (each day its changes), or ``days`` and ``transitions``
    (the same changes for every day named)."""
    if ATTR_SCHEDULE in call.data:
        if ATTR_DAYS in call.data or ATTR_TRANSITIONS in call.data:
            raise _refuse("schedule_input")
        return dict(call.data[ATTR_SCHEDULE])
    if ATTR_DAYS not in call.data or ATTR_TRANSITIONS not in call.data:
        raise _refuse("schedule_input")
    transitions = call.data[ATTR_TRANSITIONS]
    return {day: transitions for day in call.data[ATTR_DAYS]}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the room and schedule services."""

    def changed(entry: CompanionConfigEntry, room: Room | None) -> ServiceResponse:
        # Described first: the reload replaces the fleet the names are read from.
        response = describe_room(entry.runtime_data, room) if room is not None else None
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return response

    async def create_room(call: ServiceCall) -> ServiceResponse:
        entry = _loaded_entry(hass)
        data = entry.runtime_data
        members = [
            resolve_thermostat(hass, data, ref) for ref in call.data.get(ATTR_THERMOSTATS, [])
        ]
        try:
            room = data.store.create(call.data[ATTR_NAME], members)
        except RoomError as err:
            raise _refuse(err.code, **err.placeholders) from err
        return changed(entry, room)

    async def update_room(call: ServiceCall) -> ServiceResponse:
        entry = _loaded_entry(hass)
        data = entry.runtime_data
        room = resolve_room(hass, data, call.data[ATTR_ROOM])
        members = None
        if ATTR_THERMOSTATS in call.data:
            members = [resolve_thermostat(hass, data, ref) for ref in call.data[ATTR_THERMOSTATS]]
        try:
            room = data.store.update(room.id, call.data.get(ATTR_NAME), members)
        except RoomError as err:
            raise _refuse(err.code, **err.placeholders) from err
        return changed(entry, room)

    async def delete_room(call: ServiceCall) -> ServiceResponse:
        entry = _loaded_entry(hass)
        data = entry.runtime_data
        data.store.delete(resolve_room(hass, data, call.data[ATTR_ROOM]).id)
        return changed(entry, None)

    async def list_rooms(call: ServiceCall) -> ServiceResponse:
        data = _loaded_entry(hass).runtime_data
        in_rooms = {key for room in data.store.rooms.values() for key in room.members}
        return {
            "rooms": [describe_room(data, room) for room in data.store.rooms.values()],
            "thermostats_outside_rooms": sorted(
                thermostat.friendly_name
                for key, thermostat in data.coordinator.thermostats.items()
                if key not in in_rooms
            ),
        }

    async def get_schedule(call: ServiceCall) -> ServiceResponse:
        data = _loaded_entry(hass).runtime_data
        coordinator = data.coordinator
        label, keys = _target(hass, data, call)
        weeks: dict[str, Any] = {}
        for key in keys:
            thermostat = coordinator.thermostats.get(key)
            if thermostat is None:  # a member no bridge lists now
                weeks[key] = {"schedule": None, "read_at": None}
            elif call.data.get(ATTR_REFRESH):
                week = await coordinator.async_get_schedule(key)
                weeks[thermostat.friendly_name] = {"schedule": week, "read_at": "now"}
            else:
                weeks[thermostat.friendly_name] = {
                    "schedule": thermostat.schedule,
                    "read_at": thermostat.schedule_read_at,
                }
        shared, differing = schedule.common([entry["schedule"] for entry in weeks.values()])
        return {
            "target": label,
            "schedule": shared,
            "differing_days": differing,
            "thermostats": weeks,
        }

    async def set_schedule(call: ServiceCall) -> ServiceResponse:
        data = _loaded_entry(hass).runtime_data
        label, keys = _target(hass, data, call)
        results = await data.coordinator.async_set_schedule_many(keys, _days_asked(call))
        return {"target": label, "thermostats": results}

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        get_schedule,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ROOM): cv.string,
                vol.Optional(ATTR_THERMOSTAT): cv.string,
                vol.Optional(ATTR_REFRESH, default=False): cv.boolean,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        set_schedule,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_ROOM): cv.string,
                vol.Optional(ATTR_THERMOSTAT): cv.string,
                vol.Optional(ATTR_SCHEDULE): vol.Schema({vol.In(schedule.DAYS): list}),
                vol.Optional(ATTR_DAYS): vol.All(cv.ensure_list, [vol.In(schedule.DAYS)]),
                vol.Optional(ATTR_TRANSITIONS): list,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_ROOM,
        create_room,
        schema=vol.Schema(
            {vol.Required(ATTR_NAME): cv.string, vol.Optional(ATTR_THERMOSTATS): _THERMOSTATS}
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_ROOM,
        update_room,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ROOM): cv.string,
                vol.Optional(ATTR_NAME): cv.string,
                vol.Optional(ATTR_THERMOSTATS): _THERMOSTATS,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_ROOM,
        delete_room,
        schema=vol.Schema({vol.Required(ATTR_ROOM): cv.string}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_ROOMS,
        list_rooms,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
