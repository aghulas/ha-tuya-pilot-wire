"""Rooms: storage, aggregation, services, entities and the stale-entity cleanup."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_pilot_wire import async_remove_config_entry_device
from custom_components.tuya_pilot_wire.const import DOMAIN
from custom_components.tuya_pilot_wire.rooms import CompanionStore, RoomError, RoomState

from .conftest import STATE, TUYA, descriptor, fire, publish_bridge


async def call(hass: HomeAssistant, service: str, data: dict[str, Any], response: bool = True):
    result = await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=response
    )
    await hass.async_block_till_done()
    return result


async def publish(hass: HomeAssistant, name: str, **changes: Any) -> None:
    state = {k: v for k, v in {**STATE, **changes}.items() if v is not None}
    fire(hass, f"{TUYA}/{name}", state)
    await hass.async_block_till_done()


async def republish(hass: HomeAssistant, states: dict[str, dict[str, Any]] | None = None) -> None:
    """After a reload the retained topics come again."""
    await publish_bridge(
        hass,
        [
            descriptor("Thermostat A1", "dev-a1"),
            descriptor("Thermostat A2", "dev-a2"),
            descriptor("Thermostat B1", "dev-b1"),
            descriptor("Thermostat B2", "dev-b2"),
        ],
        states,
    )


@pytest.fixture
async def room(hass: HomeAssistant, fleet: MockConfigEntry) -> MockConfigEntry:
    """Room "Room A" with thermostats A1 and A2."""
    await call(hass, "create_room", {"name": "Room A", "thermostats": ["Thermostat A1", "dev-a2"]})
    await republish(hass)
    return fleet


# -- store ---------------------------------------------------------------------------------------


async def test_store_rules_and_persistence(hass: HomeAssistant) -> None:
    store = CompanionStore(hass)
    await store.async_load()
    assert store.rooms == {} and store.identities == {}

    a = store.create("  Room A ", ["k1", "k2", "k1"])
    assert (a.name, a.members) == ("Room A", ["k1", "k2"])
    with pytest.raises(RoomError, match="room_name_empty"):
        store.create("   ", [])
    with pytest.raises(RoomError, match="room_name_taken"):
        store.create("room a", [])
    with pytest.raises(RoomError, match="thermostat_in_other_room") as other:
        store.create("Room B", ["k2"])
    assert other.value.placeholders == {"room": "Room A"}

    b = store.create("Room B", ["k3"])
    with pytest.raises(RoomError, match="room_name_taken"):
        store.update(b.id, name="Room A")
    with pytest.raises(RoomError, match="thermostat_in_other_room"):
        store.update(b.id, members=["k1"])
    assert store.update(a.id, name="Room A").name == "Room A"
    assert store.update(a.id, members=["k2"]).members == ["k2"]
    assert store.room_of("k2") is a and store.room_of("k1") is None

    assert store.resolve_key("dev-1", "0x01") == "dev-1"
    assert store.resolve_key(None, "0x01") == "dev-1"
    assert store.resolve_key(None, "0x02") == "0x02"
    assert store.resolve_key("dev-3", None) == "dev-3"
    assert store.resolve_key(None, None) is None

    store.delete(b.id)
    await store.async_flush()
    again = CompanionStore(hass)
    await again.async_load()
    assert [(r.name, r.members) for r in again.rooms.values()] == [("Room A", ["k2"])]
    assert again.identities == {"0x01": "dev-1"}


# -- services ------------------------------------------------------------------------------------


async def test_create_room_by_service(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    device = next(
        device
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), fleet.entry_id)
        if (DOMAIN, "dev-a2") in device.identifiers
    )
    created = await call(
        hass, "create_room", {"name": "Room A", "thermostats": ["thermostat a1", device.id]}
    )
    assert created["name"] == "Room A"
    assert created["thermostats"] == ["Thermostat A1", "Thermostat A2"]
    await republish(hass)

    listed = await call(hass, "list_rooms", {})
    assert listed == {
        "rooms": [created],
        "thermostats_outside_rooms": ["Thermostat B1", "Thermostat B2"],
    }
    # The room has one climate; its members lost theirs, the others kept it.
    registry = er.async_get(hass)
    assert hass.states.get("climate.room_a") is not None
    assert registry.async_get("climate.thermostat_a1") is None
    assert registry.async_get("climate.thermostat_a2") is None
    assert registry.async_get("climate.thermostat_b1") is not None
    assert registry.async_get("sensor.thermostat_a1_energy") is not None


async def test_service_refusals(hass: HomeAssistant, room: MockConfigEntry) -> None:
    for service, data, key in (
        ("create_room", {"name": "Room B", "thermostats": ["Nobody"]}, "thermostat_unknown"),
        ("create_room", {"name": "Room A"}, "room_name_taken"),
        ("create_room", {"name": "Room B", "thermostats": ["dev-a1"]}, "thermostat_in_other_room"),
        ("update_room", {"room": "Nowhere", "name": "x"}, "room_unknown"),
        ("update_room", {"room": "Room A", "name": " "}, "room_name_empty"),
        ("delete_room", {"room": "Nowhere"}, "room_unknown"),
    ):
        with pytest.raises(ServiceValidationError) as refused:
            await call(hass, service, data, response=service != "delete_room")
        assert refused.value.translation_key == key, (service, data)
    assert len(room.runtime_data.store.rooms) == 1


async def test_services_need_a_loaded_entry(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(fleet.entry_id)
    with pytest.raises(ServiceValidationError) as refused:
        await call(hass, "list_rooms", {})
    assert refused.value.translation_key == "not_loaded"


async def test_update_and_delete_room(hass: HomeAssistant, room: MockConfigEntry) -> None:
    room_device = next(
        device
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), room.entry_id)
        if device.model == "Room"
    )
    assert room_device.name == "Room A"
    updated = await call(
        hass,
        "update_room",
        {"room": room_device.id, "name": "Room One", "thermostats": ["dev-a1", "dev-b1"]},
    )
    assert updated["thermostats"] == ["Thermostat A1", "Thermostat B1"]
    await republish(hass)
    registry = er.async_get(hass)
    # A2 left the room and has its own climate again; B1 joined and lost its own.
    assert hass.states.get("climate.thermostat_a2") is not None
    assert registry.async_get("climate.thermostat_b1") is None
    # The room kept its entities (same unique ids), under its new device name.
    assert registry.async_get("climate.room_a") is not None

    renamed = await call(hass, "update_room", {"room": updated["id"], "name": "Room 1"})
    assert renamed["thermostats"] == ["Thermostat A1", "Thermostat B1"]
    await republish(hass)

    await call(hass, "delete_room", {"room": "room 1"}, response=False)
    await republish(hass)
    assert room.runtime_data.store.rooms == {}
    assert registry.async_get("climate.room_a") is None
    assert registry.async_get("sensor.room_a_temperature") is None
    assert hass.states.get("climate.thermostat_a1") is not None
    assert hass.states.get("climate.thermostat_b1") is not None


# -- aggregation ---------------------------------------------------------------------------------


async def test_room_entities_when_members_agree(hass: HomeAssistant, room: MockConfigEntry) -> None:
    await publish(hass, "Thermostat A2", local_temperature=18.0, power=500.0, energy=50.25)
    climate = hass.states.get("climate.room_a")
    assert climate is not None
    assert climate.state == HVACMode.HEAT
    assert climate.attributes["supported_features"] == 0
    assert climate.attributes["current_temperature"] == 18.8  # mean of 19.5 and 18, shown at 0.1
    assert climate.attributes["target_temperature"] == 20.0
    assert climate.attributes["hvac_action"] == HVACAction.HEATING
    assert climate.attributes["members"] == ["Thermostat A1", "Thermostat A2"]
    assert climate.attributes["members_missing"] == 0
    assert climate.attributes["differing"] == []

    assert hass.states.get("sensor.room_a_temperature").state == "18.75"
    assert hass.states.get("sensor.room_a_setpoint").state == "20.0"
    assert hass.states.get("sensor.room_a_power").state == "1500.0"
    energy = hass.states.get("sensor.room_a_energy")
    assert energy.state == "150.75"
    assert energy.attributes["state_class"] == "total_increasing"
    assert hass.states.get("sensor.room_a_mode").state == "manual"
    assert hass.states.get("binary_sensor.room_a_heating").state == STATE_ON
    assert hass.states.get("binary_sensor.room_a_window").state == STATE_OFF
    assert hass.states.get("binary_sensor.room_a_fault").state == STATE_OFF
    assert hass.states.get("binary_sensor.room_a_thermostats_disagree").state == STATE_OFF
    # No room voltage or current: they have no meaning for a room.
    assert hass.states.get("sensor.room_a_voltage") is None


async def test_room_says_when_members_disagree(hass: HomeAssistant, room: MockConfigEntry) -> None:
    await publish(hass, "Thermostat A2", preset="eco", running_state="idle", fault=["e1"])
    climate = hass.states.get("climate.room_a")
    assert climate.state == HVACMode.HEAT
    assert climate.attributes["target_temperature"] is None
    assert climate.attributes["preset"] is None
    assert climate.attributes["differing"] == ["preset", "target_temperature"]
    assert hass.states.get("sensor.room_a_mode").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.room_a_setpoint").state == STATE_UNAVAILABLE
    disagree = hass.states.get("binary_sensor.room_a_thermostats_disagree")
    assert disagree.state == STATE_ON
    assert disagree.attributes["differing"] == ["preset", "target_temperature"]
    # One member heating is a room heating; one fault is a room fault.
    assert hass.states.get("binary_sensor.room_a_heating").state == STATE_ON
    fault = hass.states.get("binary_sensor.room_a_fault")
    assert fault.state == STATE_ON and fault.attributes["faults"] == ["e1"]

    await publish(hass, "Thermostat A2", system_mode="off")
    climate = hass.states.get("climate.room_a")
    assert climate.state == STATE_UNKNOWN
    assert climate.attributes["hvac_modes"] == []
    assert "system_mode" in climate.attributes["differing"]


async def test_room_sums_need_every_member(hass: HomeAssistant, room: MockConfigEntry) -> None:
    assert hass.states.get("sensor.room_a_energy").state == "201.0"
    # A member stops reporting energy: no partial sum.
    await publish(hass, "Thermostat A2", energy=None, power=None)
    assert hass.states.get("sensor.room_a_energy").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.room_a_power").state == STATE_UNAVAILABLE
    await publish(hass, "Thermostat A2")
    assert hass.states.get("sensor.room_a_energy").state == "201.0"

    # A member goes offline: sums stop, the mean and the "any" values go on with the other.
    fire(hass, f"{TUYA}/Thermostat A2/availability", {"state": "offline"})
    await publish(hass, "Thermostat A1", running_state="idle", local_temperature=17.0)
    assert hass.states.get("sensor.room_a_energy").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.room_a_temperature").state == "17.0"
    climate = hass.states.get("climate.room_a")
    assert climate.attributes["members_missing"] == 1
    assert "hvac_action" not in climate.attributes
    # "Not heating" cannot be said of the room while a member is silent; "heating" can.
    assert hass.states.get("binary_sensor.room_a_heating").state == STATE_UNAVAILABLE
    await publish(hass, "Thermostat A1", running_state="heat")
    assert hass.states.get("binary_sensor.room_a_heating").state == STATE_ON

    # Every member offline: the room is unavailable.
    fire(hass, f"{TUYA}/Thermostat A1/availability", {"state": "offline"})
    await hass.async_block_till_done()
    assert hass.states.get("climate.room_a").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.room_a_thermostats_disagree").state == STATE_UNAVAILABLE


async def test_room_state_edges(hass: HomeAssistant, room: MockConfigEntry) -> None:
    data = room.runtime_data
    stored = next(iter(data.store.rooms.values()))
    await publish(hass, "Thermostat A1", local_temperature=None, fault=None)
    await publish(hass, "Thermostat A2", local_temperature=None, fault=None)
    state = RoomState(stored, data.coordinator)
    assert state.local_temperature is None
    assert state.faults is None and state.fault is None

    empty = data.store.create("Empty", [])
    state = RoomState(empty, data.coordinator)
    assert not state.available and not state.complete
    assert state.system_mode is None and state.disagreements == []
    assert state.number("energy") is None and state.heating is None


async def test_room_climate_is_read_only(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": "climate.room_a", "hvac_mode": "off"},
            blocking=True,
        )
    mqtt_mock.async_publish.assert_not_called()


# -- devices -------------------------------------------------------------------------------------


async def test_device_removal_is_allowed_only_for_what_is_gone(
    hass: HomeAssistant, room: MockConfigEntry
) -> None:
    devices = dr.async_get(hass)
    by_identifier = {
        identifier: device
        for device in dr.async_entries_for_config_entry(devices, room.entry_id)
        for _, identifier in device.identifiers
    }

    async def remove(device_id: str) -> bool:
        device = devices.async_get(device_id)
        assert device is not None
        return await async_remove_config_entry_device(hass, room, device)

    room_id = next(iter(room.runtime_data.store.rooms))
    assert not await remove(by_identifier["dev-b1"].id)
    assert not await remove(by_identifier[f"room_{room_id}"].id)
    # B1 leaves the bridge's list: its device can now be removed.
    fire(
        hass,
        f"{TUYA}/bridge/devices",
        [descriptor("Thermostat A1", "dev-a1"), descriptor("Thermostat A2", "dev-a2")],
    )
    await hass.async_block_till_done()
    assert await remove(by_identifier["dev-b1"].id)


async def test_an_unknown_value_is_not_a_disagreement(
    hass: HomeAssistant, room: MockConfigEntry
) -> None:
    # A2's last read brought neither its mode nor its preset.
    await publish(hass, "Thermostat A2", system_mode=None, preset=None)
    climate = hass.states.get("climate.room_a")
    assert climate.state == STATE_UNKNOWN
    assert climate.attributes["differing"] == []
    assert climate.attributes["preset"] is None
    assert hass.states.get("binary_sensor.room_a_thermostats_disagree").state == STATE_OFF
    # A known difference is still one, whatever else is unknown.
    await publish(hass, "Thermostat A2", system_mode="off", preset=None)
    assert hass.states.get("climate.room_a").attributes["differing"] == ["system_mode"]
