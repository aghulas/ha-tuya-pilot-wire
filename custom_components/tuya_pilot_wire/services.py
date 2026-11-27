"""Room services: create, update, delete and list the rooms the Companion keeps.

They change Home Assistant storage only; nothing is sent to a bridge or a thermostat. After a
change the entry reloads, because the set of entities follows the rooms.

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

from .const import (
    ATTR_NAME,
    ATTR_ROOM,
    ATTR_THERMOSTATS,
    DOMAIN,
    SERVICE_CREATE_ROOM,
    SERVICE_DELETE_ROOM,
    SERVICE_LIST_ROOMS,
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


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the room services."""

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
