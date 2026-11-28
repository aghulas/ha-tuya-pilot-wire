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
from .const import SET_KEYS, SET_PRESETS
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


def _info(info: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """A bridge's `bridge/info`, redacted, its `writes` naming thermostats by their number."""
    kept = async_redact_data({k: v for k, v in info.items() if k != "writes"}, TO_REDACT)
    writes = info.get("writes")
    if isinstance(writes, dict):
        writes = dict(writes)
        if isinstance(writes.get("device"), str):
            writes["device"] = names.get(writes["device"], "unknown")
        if isinstance(writes.get("devices"), list):
            writes["devices"] = [
                names.get(name, "unknown") if isinstance(name, str) else "unknown"
                for name in writes["devices"]
            ]
        if isinstance(writes.get("closed"), str):
            # A reason may quote a thermostat's name.
            for name, ref in sorted(names.items(), key=lambda item: -len(item[0])):
                writes["closed"] = writes["closed"].replace(name, ref)
        # `device` is now a number, not a name: the rest is redacted as everywhere.
        kept["writes"] = async_redact_data(writes, TO_REDACT - {"device"})
    return kept


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CompanionConfigEntry
) -> dict[str, Any]:
    """Diagnostics of the entry."""
    coordinator = entry.runtime_data.coordinator
    store = entry.runtime_data.store
    refs = {key: f"thermostat_{index}" for index, key in enumerate(coordinator.thermostats, 1)}
    names = {
        thermostat.friendly_name: refs[key] for key, thermostat in coordinator.thermostats.items()
    }

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
            # Also listed by a second bridge (a move between bridges in progress), and whether
            # that listing is usable there.
            "shadow": (
                {
                    "bridge": shadow.prefix,
                    "online": shadow.online,
                    "has_ieee_address": shadow.ieee_address is not None,
                }
                if (shadow := coordinator.shadows.get(key)) is not None
                else None
            ),
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
        "set_keys": sorted(SET_KEYS),
        "set_presets": list(SET_PRESETS),
        "bridges": {
            prefix: {
                "online": coordinator.bridge_online.get(prefix),
                "info": _info(coordinator.bridge_info.get(prefix, {}), names),
                "open_for": sorted(
                    refs[key]
                    for key in coordinator.thermostats
                    if coordinator.thermostats[key].prefix == prefix
                    and any(coordinator.supports_set(key, set_key) for set_key in SET_KEYS)
                ),
            }
            for prefix in coordinator.prefixes
        },
        "thermostats": thermostats,
        "rooms": rooms,
        "known_identities": len(store.identities),
    }
