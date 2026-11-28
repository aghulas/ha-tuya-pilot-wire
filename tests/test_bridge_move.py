"""A thermostat moving between bridges (milestone M5, docs/z2m-parity.md).

The same thermostat can be listed by both bridges for a while: the Tuya bridge lists it until the
account drops it, Zigbee2MQTT from its interview on. It must keep its entities and its room, be
shown from one bridge only, and never be written to through a bridge that has not opened it.
"""

from __future__ import annotations

import json
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_pilot_wire.const import DOMAIN
from custom_components.tuya_pilot_wire.diagnostics import async_get_config_entry_diagnostics

from .conftest import STATE, TUYA, Z2M, descriptor, fire, publish_bridge, z2m_descriptor

A1 = "thermostat_a1"
IEEE = "0xa4c1380000000001"

# What Zigbee2MQTT publishes with the converter of zigbee2mqtt/ (no `preset` while the mode index
# table is not established; `mode_index` and `linkquality` are ignored by the Companion).
Z2M_STATE: dict[str, Any] = {
    "local_temperature": 20.0,
    "current_heating_setpoint": 19.0,
    "system_mode": "heat",
    "running_state": "idle",
    "window_open": False,
    "fault": [],
    "energy": 101.0,
    "power": 0,
    "mode_index": 3,
    "linkquality": 120,
}


def state_of(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def publish(hass: HomeAssistant, topic: str, payload: Any) -> None:
    fire(hass, topic, payload)
    await hass.async_block_till_done()


async def on_tuya(hass: HomeAssistant) -> None:
    await publish_bridge(hass, [descriptor("Thermostat A1", "dev-a1", IEEE.upper())])


async def on_z2m(hass: HomeAssistant) -> None:
    await publish_bridge(hass, [z2m_descriptor("heater", IEEE)], {"heater": Z2M_STATE}, prefix=Z2M)


async def test_listed_by_both_bridges_it_stays_where_it_is_usable(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    coordinator = entry.runtime_data.coordinator
    await on_tuya(hass)
    await on_z2m(hass)
    # Both list it: shown from the bridge that held it, the other listing waits.
    assert coordinator.thermostats["dev-a1"].prefix == TUYA
    assert coordinator.shadows["dev-a1"].prefix == Z2M
    assert state_of(hass, f"sensor.{A1}_energy") == "100.5"
    assert hass.states.get("sensor.heater_energy") is None

    # The Tuya copy goes offline (it left the gateway): the Zigbee2MQTT one is shown.
    await publish(hass, f"{TUYA}/Thermostat A1/availability", {"state": "offline"})
    assert coordinator.thermostats["dev-a1"].prefix == Z2M
    assert state_of(hass, f"sensor.{A1}_energy") == "101.0"
    assert state_of(hass, f"sensor.{A1}_temperature") == "20.0"

    # A late message on the Tuya topics does not bring it back while Zigbee2MQTT is usable.
    await publish(hass, f"{TUYA}/Thermostat A1/availability", {"state": "online"})
    await publish(hass, f"{TUYA}/Thermostat A1", {**STATE, "energy": 1.0})
    assert coordinator.thermostats["dev-a1"].prefix == Z2M
    assert state_of(hass, f"sensor.{A1}_energy") == "101.0"
    # Each copy keeps reading its own topics.
    await publish(hass, f"{Z2M}/heater", {**Z2M_STATE, "energy": 101.5})
    assert state_of(hass, f"sensor.{A1}_energy") == "101.5"

    # The Tuya bridge stops listing it: the shadow goes, nothing changes on screen.
    await publish(hass, f"{TUYA}/bridge/devices", [])
    assert "dev-a1" not in coordinator.shadows
    assert state_of(hass, f"sensor.{A1}_energy") == "101.5"


async def test_the_holder_stops_listing_it_and_the_shadow_takes_over_at_once(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await on_tuya(hass)
    await on_z2m(hass)
    await publish(hass, f"{TUYA}/bridge/devices", [])
    coordinator = entry.runtime_data.coordinator
    assert coordinator.thermostats["dev-a1"].prefix == Z2M
    assert coordinator.shadows == {}
    # With the state Zigbee2MQTT had already published, without waiting for the next one.
    assert state_of(hass, f"sensor.{A1}_energy") == "101.0"


async def test_back_to_the_tuya_gateway(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The rollback: Zigbee2MQTT holds it, the Tuya bridge lists it again."""
    coordinator = entry.runtime_data.coordinator
    await on_tuya(hass)
    await publish(hass, f"{TUYA}/bridge/devices", [])
    await on_z2m(hass)
    assert coordinator.thermostats["dev-a1"].prefix == Z2M

    await on_tuya(hass)
    assert coordinator.thermostats["dev-a1"].prefix == Z2M
    assert coordinator.shadows["dev-a1"].prefix == TUYA
    # Zigbee2MQTT says the device is gone (or the bridge stops): the Tuya copy is shown.
    await publish(hass, f"{Z2M}/heater/availability", {"state": "offline"})
    assert coordinator.thermostats["dev-a1"].prefix == TUYA
    assert state_of(hass, f"sensor.{A1}_energy") == "100.5"
    await publish(hass, f"{Z2M}/bridge/devices", [])
    assert coordinator.shadows == {}
    assert coordinator.thermostats["dev-a1"].prefix == TUYA


async def test_back_on_the_gateway_with_a_new_device_id(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Re-pairing to the Tuya gateway can give a new device id: the IEEE address keeps the key."""
    await on_tuya(hass)
    await hass.services.async_call(
        DOMAIN, "create_room", {"name": "Room A", "thermostats": ["dev-a1"]}, blocking=True
    )
    await publish(hass, f"{TUYA}/bridge/devices", [])
    await on_z2m(hass)
    await publish(hass, f"{Z2M}/bridge/devices", [])
    await publish_bridge(hass, [descriptor("Thermostat A1", "dev-new", IEEE)])
    coordinator = entry.runtime_data.coordinator
    assert set(coordinator.thermostats) == {"dev-a1"}
    assert entry.runtime_data.store.room_of("dev-a1").name == "Room A"
    assert state_of(hass, f"sensor.{A1}_energy") == "100.5"
    # A later listing by device id alone (no node id) still finds it.
    await publish(hass, f"{TUYA}/bridge/devices", [descriptor("Thermostat A1", "dev-new")])
    assert set(coordinator.thermostats) == {"dev-a1"}


async def test_a_bridge_going_offline_hands_over(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    coordinator = entry.runtime_data.coordinator
    await on_tuya(hass)
    await on_z2m(hass)
    await publish(hass, f"{TUYA}/bridge/state", {"state": "offline"})
    assert coordinator.thermostats["dev-a1"].prefix == Z2M
    # Neither usable: it stays where it is, unavailable.
    await publish(hass, f"{Z2M}/bridge/state", {"state": "offline"})
    assert coordinator.thermostats["dev-a1"].prefix == Z2M
    assert state_of(hass, f"sensor.{A1}_energy") == STATE_UNAVAILABLE


async def test_room_and_unique_ids_survive_the_move(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await publish_bridge(
        hass,
        [descriptor("Thermostat A1", "dev-a1", IEEE), descriptor("Thermostat A2", "dev-a2")],
    )
    await hass.services.async_call(
        DOMAIN,
        "create_room",
        {"name": "Room A", "thermostats": ["dev-a1", "dev-a2"]},
        blocking=True,
    )
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    unique_ids = {e.unique_id for e in registry.entities.values() if e.platform == DOMAIN}

    await publish(hass, f"{TUYA}/bridge/devices", [descriptor("Thermostat A2", "dev-a2")])
    await on_z2m(hass)
    store = entry.runtime_data.store
    assert store.room_of("dev-a1") is not None and store.room_of("dev-a1").name == "Room A"
    assert {e.unique_id for e in registry.entities.values() if e.platform == DOMAIN} == unique_ids
    # The room reads the moved member from Zigbee2MQTT: mean of 20.0 and 19.5.
    assert state_of(hass, "sensor.room_a_temperature") == "19.75"


async def test_no_write_through_a_bridge_that_did_not_open_it(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    coordinator = entry.runtime_data.coordinator
    await on_tuya(hass)
    await publish(
        hass,
        f"{TUYA}/bridge/info",
        {
            "contract": 5,
            "read_only": False,
            "writes": {"keys": ["preset"], "devices": ["Thermostat A1"]},
        },
    )
    assert coordinator.supports_set("dev-a1", "preset")
    await on_z2m(hass)
    await publish(hass, f"{TUYA}/bridge/devices", [])
    # Now on Zigbee2MQTT, whose `bridge/info` opens nothing: closed, whatever the Tuya bridge says.
    await publish(hass, f"{Z2M}/bridge/info", {"version": "2.14.3"})
    assert coordinator.thermostats["dev-a1"].prefix == Z2M
    assert not coordinator.supports_set("dev-a1", "preset")


async def test_identity_needs_the_ieee_address_seen_on_the_tuya_bridge(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Without the pair seen once, the Zigbee2MQTT listing is another thermostat."""
    await publish_bridge(hass, [descriptor("Thermostat A1", "dev-a1")])
    await publish(hass, f"{TUYA}/bridge/devices", [])
    await on_z2m(hass)
    coordinator = entry.runtime_data.coordinator
    assert set(coordinator.thermostats) == {IEEE}
    assert state_of(hass, "sensor.heater_energy") == "101.0"


async def test_diagnostics_show_the_shadow_without_identifiers(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await on_tuya(hass)
    await on_z2m(hass)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    (thermostat,) = diagnostics["thermostats"]
    assert thermostat["shadow"] == {"bridge": Z2M, "online": True, "has_ieee_address": True}
    text = json.dumps(diagnostics)
    assert IEEE not in text and "dev-a1" not in text and "heater" not in text
