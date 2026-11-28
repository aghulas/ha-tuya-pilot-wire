"""Options flow (bridges and rooms), diagnostics, and entry setup edges."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_pilot_wire import entry_prefixes
from custom_components.tuya_pilot_wire.const import CONF_MQTT_PREFIXES, DOMAIN
from custom_components.tuya_pilot_wire.diagnostics import async_get_config_entry_diagnostics

from .conftest import STATE, TUYA, Z2M, descriptor, fire, publish_bridge


async def step(hass: HomeAssistant, entry: MockConfigEntry, *inputs: dict[str, Any]) -> Any:
    """Open the options flow and feed it the inputs in order; return the last result."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    for user_input in inputs:
        result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
    await hass.async_block_till_done()
    return result


async def test_menu_follows_the_rooms(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    result = await step(hass, fleet)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["bridges", "add_room"]
    fleet.runtime_data.store.create("Room A", [])
    result = await step(hass, fleet)
    assert result["menu_options"] == ["bridges", "add_room", "edit_room", "delete_room"]


async def test_options_need_a_loaded_entry(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(fleet.entry_id)
    result = await step(hass, fleet)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


async def test_change_the_bridges(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    result = await step(hass, fleet, {"next_step_id": "bridges"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MQTT_PREFIXES: "a/b"}
    )
    assert result["errors"] == {CONF_MQTT_PREFIXES: "invalid_prefixes"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MQTT_PREFIXES: "tuyapilot2mqtt"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry_prefixes(fleet) == [TUYA]
    # Reloaded on the new prefixes.
    assert fleet.state is ConfigEntryState.LOADED
    assert fleet.runtime_data.coordinator.prefixes == (TUYA,)


async def test_rooms_through_the_options_flow(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    result = await step(hass, fleet, {"next_step_id": "add_room"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": " ", "thermostats": ["dev-a1"]}
    )
    assert result["errors"] == {"base": "room_name_empty"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Room A", "thermostats": ["dev-a1", "dev-a2"]}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    store = fleet.runtime_data.store
    (room,) = store.rooms.values()
    assert (room.name, room.members) == ("Room A", ["dev-a1", "dev-a2"])
    assert hass.states.get("climate.room_a") is not None

    # A second room: only the thermostats outside any room are offered.
    await publish_bridge(
        hass, [descriptor(f"Thermostat {n}", f"dev-{n.lower()}") for n in ("A1", "A2", "B1", "B2")]
    )
    store.create("Room B", ["dev-b1"])
    result = await step(hass, fleet, {"next_step_id": "add_room"})
    offered = result["data_schema"].schema["thermostats"].config["options"]
    assert [option["value"] for option in offered] == ["dev-b2"]

    # Edit room A: its own thermostats first, then the free ones; a name already taken is refused.
    result = await step(hass, fleet, {"next_step_id": "edit_room"}, {"room": room.id})
    assert result["step_id"] == "room"
    offered = result["data_schema"].schema["thermostats"].config["options"]
    assert [option["value"] for option in offered] == ["dev-a1", "dev-a2", "dev-b2"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Room B", "thermostats": ["dev-a1"]}
    )
    assert result["errors"] == {"base": "room_name_taken"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"name": "Room One", "thermostats": ["dev-a1", "dev-b2"]}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    room = fleet.runtime_data.store.rooms[room.id]
    assert (room.name, room.members) == ("Room One", ["dev-a1", "dev-b2"])

    # A member the bridge no longer lists is still offered for its room, by its key.
    fire(hass, f"{TUYA}/bridge/devices", [descriptor("Thermostat B2", "dev-b2")])
    await hass.async_block_till_done()
    result = await step(hass, fleet, {"next_step_id": "edit_room"}, {"room": room.id})
    offered = result["data_schema"].schema["thermostats"].config["options"]
    assert {"value": "dev-a1", "label": "dev-a1"} in offered

    result = await step(hass, fleet, {"next_step_id": "delete_room"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"room": room.id})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [r.name for r in fleet.runtime_data.store.rooms.values()] == ["Room B"]


async def test_diagnostics_leak_no_identity(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    secret_state = {
        **STATE,
        "tuya": {"mode": "manual", "dev_id": "dev-a1", "gateway": "gateway-0001"},
    }
    await publish_bridge(
        hass,
        [descriptor("Thermostat A1", "dev-a1", "0xa1"), descriptor("Thermostat A2", "dev-a2")],
        {"Thermostat A1": secret_state},
    )
    fire(
        hass,
        f"{TUYA}/bridge/info",
        {"version": "0.1.0", "channels": {"sharing": {"state": "up", "account": "someone"}}},
    )
    await hass.async_block_till_done()
    store = fleet.runtime_data.store
    store.create("Room A", ["dev-a1", "dev-a2", "dev-gone"])

    diagnostics = await async_get_config_entry_diagnostics(hass, fleet)
    text = json.dumps(diagnostics)
    for leak in ("dev-a1", "dev-a2", "0xa1", "gateway-0001", "Thermostat A", "Room A", "someone"):
        assert leak not in text, leak

    assert diagnostics["prefixes"] == [Z2M, TUYA]
    assert diagnostics["set_keys"] == [
        "child_lock",
        "current_heating_setpoint",
        "holiday_temperature",
        "local_temperature_calibration",
        "preset",
        "window_detection",
    ]
    assert diagnostics["bridges"][TUYA]["online"] is True
    assert diagnostics["bridges"][TUYA]["info"]["version"] == "0.1.0"
    assert diagnostics["bridges"][Z2M] == {
        "online": None,
        "info": {},
        "open_for": [],
        "open_keys": {},
        "open_presets": {},
    }
    first = diagnostics["thermostats"][0]
    assert first["ref"] == "thermostat_1" and first["identity"] == "tuya"
    assert first["has_ieee_address"] is True and first["available"] is True
    assert first["state"]["local_temperature"] == 19.5
    assert first["state"]["tuya"]["mode"] == "manual"
    (room,) = diagnostics["rooms"]
    assert room["members"] == ["thermostat_1", "thermostat_2", "unknown"]
    assert room["members_missing"] == 1
    assert room["energy"] is None and room["local_temperature"] == 19.5
    assert diagnostics["known_identities"] == 1


async def test_setup_waits_for_mqtt(hass: HomeAssistant, mqtt_mock: Any) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_MQTT_PREFIXES: [TUYA]})
    entry.add_to_hass(hass)
    with patch(
        "custom_components.tuya_pilot_wire.mqtt.async_wait_for_mqtt_client", return_value=False
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_stops_listening(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    coordinator = fleet.runtime_data.coordinator
    assert await hass.config_entries.async_unload(fleet.entry_id)
    assert fleet.state is ConfigEntryState.NOT_LOADED
    assert coordinator._unsubscribe == []
    fire(hass, f"{TUYA}/Thermostat A1", {**STATE, "local_temperature": 1.0})
    await hass.async_block_till_done()
    assert coordinator.thermostats["dev-a1"].local_temperature == 19.5
