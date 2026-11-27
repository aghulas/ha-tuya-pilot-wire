"""Tuya Pilot Wire Companion: pilot-wire thermostats read from MQTT bridges.

Read only for now: the entry subscribes to the configured bridge prefixes, keeps rooms in Home
Assistant storage and creates `climate`, `sensor` and `binary_sensor` entities. Writes arrive
with milestone M4, one route at a time (docs/roadmap.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import CONF_MQTT_PREFIXES, DATA_HANDOVER, DOMAIN, PLATFORMS
from .coordinator import CompanionCoordinator
from .entity import ROOM_PREFIX, room_identifier
from .rooms import CompanionStore
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class CompanionData:
    """What an entry holds while it is loaded."""

    coordinator: CompanionCoordinator
    store: CompanionStore


type CompanionConfigEntry = ConfigEntry[CompanionData]


def entry_prefixes(entry: ConfigEntry) -> list[str]:
    """Bridge prefixes of an entry: the options when set, else what the config flow stored."""
    return list(entry.options.get(CONF_MQTT_PREFIXES) or entry.data[CONF_MQTT_PREFIXES])


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the room services."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CompanionConfigEntry) -> bool:
    """Set up the Companion from a config entry."""
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT is not available")

    store = CompanionStore(hass)
    await store.async_load()
    coordinator = CompanionCoordinator(hass, entry_prefixes(entry), store.resolve_key)
    previous: CompanionCoordinator | None = hass.data.pop(DATA_HANDOVER, None)
    if previous is not None:
        coordinator.adopt(previous)
    entry.runtime_data = CompanionData(coordinator, store)

    _remove_stale(hass, entry, store)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start()
    entry.async_on_unload(coordinator.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CompanionConfigEntry) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.store.async_flush()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        # A reload sets the entry up again at once: it starts from this fleet (see `adopt`).
        hass.data[DATA_HANDOVER] = entry.runtime_data.coordinator
    return unloaded


async def _async_options_updated(hass: HomeAssistant, entry: CompanionConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _remove_stale(hass: HomeAssistant, entry: ConfigEntry, store: CompanionStore) -> None:
    """Drop what the rooms no longer justify: deleted rooms, and the own `climate` of a thermostat
    that joined a room. Entities of a thermostat a bridge stopped listing are left alone: they are
    unavailable, and the user removes the device when it is gone for good.
    """
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        for domain, identifier in device.identifiers:
            if (
                domain == DOMAIN
                and identifier.startswith(ROOM_PREFIX)
                and identifier.removeprefix(ROOM_PREFIX) not in store.rooms
            ):
                devices.async_remove_device(device.id)
    entities = er.async_get(hass)
    for room in store.rooms.values():
        for key in room.members:
            entity_id = entities.async_get_entity_id("climate", DOMAIN, f"{key}_climate")
            if entity_id is not None:
                entities.async_remove(entity_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: CompanionConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a device that no bridge lists and no room defines any more."""
    data = entry.runtime_data
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        if identifier in data.coordinator.thermostats:
            return False
        if any(identifier == room_identifier(room_id) for room_id in data.store.rooms):
            return False
    return True
