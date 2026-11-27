"""Diagnostics, redacted for a public issue tracker.

Never in the output: a device id, an IEEE address, a gateway id, a key, an account, an address,
nor a name given on site (thermostats and rooms are numbered instead). Measured values, modes and
the shape of what the bridges publish are kept: they are what a diagnosis needs.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import CompanionConfigEntry
from .const import OPEN_SET_KEYS, TRIAL_SET_KEYS
from .rooms import RoomState

TO_REDACT = {
    "access_id",
    "access_secret",
    "account",
    "dev_id",
    "device",
    "email",
    "endpoint",
    "friendly_name",
    "gateway",
    "gateway_id",
    "host",
    "id",
    "ieee_address",
    "ip",
    "key",
    "local_key",
    "mac",
    "name",
    "node_id",
    "password",
    "secret",
    "session",
    "token",
    "uid",
    "user",
    "username",
    "uuid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CompanionConfigEntry
) -> dict[str, Any]:
    """Diagnostics of the entry."""
    coordinator = entry.runtime_data.coordinator
    store = entry.runtime_data.store
    trial = coordinator.trial_thermostat
    refs = {key: f"thermostat_{index}" for index, key in enumerate(coordinator.thermostats, 1)}

    thermostats = [
        {
            "ref": refs[key],
            "bridge": thermostat.prefix,
            "identity": "ieee" if key == thermostat.ieee_address else "tuya",
            "has_ieee_address": thermostat.ieee_address is not None,
            "vendor": thermostat.vendor,
            "model": thermostat.model,
            "online": thermostat.online,
            "available": coordinator.available(key),
            "state": async_redact_data(thermostat.state, TO_REDACT),
        }
        for key, thermostat in coordinator.thermostats.items()
    ]

    rooms = []
    for index, room in enumerate(store.rooms.values(), 1):
        state = RoomState(room, coordinator)
        rooms.append(
            {
                "ref": f"room_{index}",
                "members": [refs.get(key, "unknown") for key in room.members],
                "members_missing": state.missing,
                "local_temperature": state.local_temperature,
                "system_mode": state.system_mode,
                "preset": state.preset,
                "target_temperature": state.target_temperature,
                "differing": state.disagreements,
                "heating": state.heating,
                "window_open": state.window_open,
                "fault": state.fault,
                "power": state.number("power"),
                "energy": state.number("energy"),
            }
        )

    return {
        "prefixes": list(coordinator.prefixes),
        "open_set_keys": sorted(OPEN_SET_KEYS),
        "trial_set_keys": sorted(TRIAL_SET_KEYS),
        "trial_thermostat": refs.get(trial, "unknown") if trial else None,
        "bridges": {
            prefix: {
                "online": coordinator.bridge_online.get(prefix),
                "info": async_redact_data(coordinator.bridge_info.get(prefix, {}), TO_REDACT),
            }
            for prefix in coordinator.prefixes
        },
        "thermostats": thermostats,
        "rooms": rooms,
        "known_identities": len(store.identities),
    }
