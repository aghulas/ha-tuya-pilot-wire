"""The Companion on a mocked broker: fleet, availability and entities, read only."""

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

from custom_components.tuya_pilot_wire.const import DOMAIN

from .conftest import STATE, TUYA, Z2M, descriptor, fire, publish_bridge, z2m_descriptor

A1 = "thermostat_a1"


def state_of(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def publish(hass: HomeAssistant, topic: str, payload: Any) -> None:
    fire(hass, topic, payload)
    await hass.async_block_till_done()


async def test_nothing_before_a_bridge_speaks(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert entry.runtime_data.coordinator.thermostats == {}
    assert hass.states.async_all("climate") == []


async def test_thermostat_entities(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    climate = hass.states.get(f"climate.{A1}")
    assert climate is not None
    assert climate.state == HVACMode.HEAT
    assert climate.attributes["hvac_modes"] == [HVACMode.HEAT]
    assert climate.attributes["supported_features"] == 0
    assert climate.attributes["hvac_action"] == HVACAction.HEATING
    assert climate.attributes["current_temperature"] == 19.5
    assert climate.attributes["target_temperature"] == 20.0
    assert "temperature" not in climate.attributes
    assert climate.attributes["preset"] == "manual"
    assert climate.attributes["eco_temperature"] == 16.0

    assert state_of(hass, f"sensor.{A1}_temperature") == "19.5"
    assert state_of(hass, f"sensor.{A1}_setpoint") == "20.0"
    assert state_of(hass, f"sensor.{A1}_power") == "1000.0"
    assert state_of(hass, f"sensor.{A1}_voltage") == "230.0"
    assert state_of(hass, f"sensor.{A1}_current") == "4.35"
    assert state_of(hass, f"sensor.{A1}_mode") == "manual"
    energy = hass.states.get(f"sensor.{A1}_energy")
    assert energy is not None and energy.state == "100.5"
    assert energy.attributes["state_class"] == "total_increasing"
    assert energy.attributes["device_class"] == "energy"
    assert energy.attributes["unit_of_measurement"] == "kWh"

    assert state_of(hass, f"binary_sensor.{A1}_heating") == STATE_ON
    assert state_of(hass, f"binary_sensor.{A1}_window") == STATE_OFF
    fault = hass.states.get(f"binary_sensor.{A1}_fault")
    assert fault is not None and fault.state == STATE_OFF
    assert fault.attributes["faults"] == []

    device = next(
        device
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), fleet.entry_id)
        if (DOMAIN, "dev-a1") in device.identifiers
    )
    assert (device.name, device.manufacturer, device.model) == (
        "Thermostat A1",
        "Tuya",
        "TS0601_fu1bfwza",
    )


async def test_no_entity_for_a_property_never_published(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await publish_bridge(
        hass,
        [descriptor("Thermostat A1", "dev-a1")],
        {"Thermostat A1": {"local_temperature": 18.0, "system_mode": "heat"}},
    )
    assert state_of(hass, f"sensor.{A1}_temperature") == "18.0"
    for missing in ("power", "energy", "voltage", "current", "mode"):
        assert hass.states.get(f"sensor.{A1}_{missing}") is None
    assert hass.states.get(f"binary_sensor.{A1}_heating") is None
    # It appears the day the bridge publishes it.
    await publish(hass, f"{TUYA}/Thermostat A1", {"local_temperature": 18.0, "power": 0})
    assert state_of(hass, f"sensor.{A1}_power") == "0.0"


async def test_a_property_that_disappears_makes_its_entity_unavailable(
    hass: HomeAssistant, fleet: MockConfigEntry
) -> None:
    idle = {k: v for k, v in STATE.items() if k not in ("voltage", "current")}
    await publish(hass, f"{TUYA}/Thermostat A1", {**idle, "running_state": "idle", "power": 0})
    assert state_of(hass, f"sensor.{A1}_voltage") == STATE_UNAVAILABLE
    assert state_of(hass, f"sensor.{A1}_current") == STATE_UNAVAILABLE
    assert state_of(hass, f"sensor.{A1}_power") == "0.0"
    assert state_of(hass, f"binary_sensor.{A1}_heating") == STATE_OFF
    climate = hass.states.get(f"climate.{A1}")
    assert climate is not None and climate.attributes["hvac_action"] == HVACAction.IDLE


async def test_program_preset_has_no_target(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    await publish(hass, f"{TUYA}/Thermostat A1", {**STATE, "preset": "program"})
    climate = hass.states.get(f"climate.{A1}")
    assert climate is not None
    assert climate.attributes["target_temperature"] is None
    assert state_of(hass, f"sensor.{A1}_setpoint") == STATE_UNAVAILABLE
    assert climate.attributes["current_heating_setpoint"] == 20.0


async def test_off_and_unknown_mode(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    await publish(hass, f"{TUYA}/Thermostat A1", {**STATE, "system_mode": "off"})
    climate = hass.states.get(f"climate.{A1}")
    assert climate is not None and climate.state == HVACMode.OFF
    assert climate.attributes["hvac_action"] == HVACAction.OFF
    await publish(hass, f"{TUYA}/Thermostat A1", {"local_temperature": 18.0})
    climate = hass.states.get(f"climate.{A1}")
    assert climate is not None and climate.state == STATE_UNKNOWN
    assert climate.attributes["hvac_modes"] == []
    assert "hvac_action" not in climate.attributes or climate.attributes["hvac_action"] is None


async def test_availability(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    await publish(hass, f"{TUYA}/Thermostat A1/availability", {"state": "offline"})
    assert state_of(hass, f"climate.{A1}") == STATE_UNAVAILABLE
    assert state_of(hass, f"sensor.{A1}_temperature") == STATE_UNAVAILABLE
    assert state_of(hass, "sensor.thermostat_a2_temperature") == "19.5"
    await publish(hass, f"{TUYA}/Thermostat A1/availability", "online")
    assert state_of(hass, f"climate.{A1}") == HVACMode.HEAT

    await publish(hass, f"{TUYA}/bridge/state", b"offline")
    assert state_of(hass, f"climate.{A1}") == STATE_UNAVAILABLE
    assert state_of(hass, "sensor.thermostat_a2_energy") == STATE_UNAVAILABLE
    await publish(hass, f"{TUYA}/bridge/state", {"state": "online"})
    assert state_of(hass, "sensor.thermostat_a2_energy") == "100.5"


async def test_a_thermostat_removed_from_the_list_goes_unavailable(
    hass: HomeAssistant, fleet: MockConfigEntry
) -> None:
    await publish(hass, f"{TUYA}/bridge/devices", [descriptor("Thermostat A2", "dev-a2")])
    assert state_of(hass, f"climate.{A1}") == STATE_UNAVAILABLE
    assert state_of(hass, "climate.thermostat_a2") == HVACMode.HEAT
    assert list(fleet.runtime_data.coordinator.thermostats) == ["dev-a2"]
    # A state still published under the old name is not picked up.
    await publish(hass, f"{TUYA}/Thermostat A1", STATE)
    assert state_of(hass, f"climate.{A1}") == STATE_UNAVAILABLE


async def test_retained_messages_in_any_order(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    fire(hass, f"{TUYA}/Thermostat A1", STATE)
    fire(hass, f"{TUYA}/Thermostat A1/availability", {"state": "online"})
    fire(hass, f"{TUYA}/Stranger", {"local_temperature": 1})
    fire(hass, f"{TUYA}/bridge/devices", [descriptor("Thermostat A1", "dev-a1")])
    await hass.async_block_till_done()
    # The bridge state has not come yet: nothing is shown as available.
    assert state_of(hass, f"climate.{A1}") == STATE_UNAVAILABLE
    await publish(hass, f"{TUYA}/bridge/state", {"state": "online"})
    assert state_of(hass, f"sensor.{A1}_temperature") == "19.5"
    assert entry.runtime_data.coordinator._early == {}


async def test_rename_keeps_the_entities_and_drops_the_old_state(
    hass: HomeAssistant, fleet: MockConfigEntry
) -> None:
    await publish(hass, f"{TUYA}/bridge/devices", [descriptor("Renamed", "dev-a1")])
    # Same entity, and nothing read under the old topic is shown under the new one.
    assert state_of(hass, f"climate.{A1}") == STATE_UNKNOWN
    await publish(hass, f"{TUYA}/Renamed", {**STATE, "local_temperature": 21.0})
    assert state_of(hass, f"sensor.{A1}_temperature") == "21.0"
    await publish(hass, f"{TUYA}/Thermostat A1", {**STATE, "local_temperature": 1.0})
    assert state_of(hass, f"sensor.{A1}_temperature") == "21.0"


async def test_descriptor_refresh_keeps_the_state(
    hass: HomeAssistant, fleet: MockConfigEntry
) -> None:
    entry_a1 = descriptor("Thermostat A1", "dev-a1", "0x0a")
    await publish(hass, f"{TUYA}/bridge/devices", [entry_a1])
    assert state_of(hass, f"sensor.{A1}_temperature") == "19.5"
    assert fleet.runtime_data.coordinator.thermostats["dev-a1"].ieee_address == "0x0a"


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("bridge/devices", "not json"),
        ("bridge/devices", {"a": 1}),
        ("bridge/state", "maybe"),
        ("bridge/state", {"state": 3}),
        ("bridge/info", "[]"),
        ("bridge/logging", {"level": "info"}),
        ("bridge/response/device/set", {"status": "error"}),
        ("Thermostat A1", "not json"),
        ("Thermostat A1", b"\xff\xfe"),
        ("Thermostat A1", [1]),
        ("Thermostat A1/availability", "maybe"),
        ("Thermostat A1/set", {"system_mode": "off"}),
        ("Thermostat A1/get", {"system_mode": ""}),
        ("Unknown thermostat", STATE),
    ],
)
async def test_malformed_and_foreign_messages_change_nothing(
    hass: HomeAssistant, fleet: MockConfigEntry, topic: str, payload: Any
) -> None:
    await publish(hass, f"{TUYA}/{topic}", payload)
    assert state_of(hass, f"climate.{A1}") == HVACMode.HEAT
    assert len(fleet.runtime_data.coordinator.thermostats) == 4


async def test_other_prefixes_are_ignored(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    coordinator = fleet.runtime_data.coordinator
    coordinator.process_message("elsewhere/bridge/state", "offline")
    coordinator.process_message(TUYA, "offline")
    assert coordinator.bridge_online == {Z2M: None, TUYA: True}
    assert not coordinator.supports_set("dev-a1", "current_heating_setpoint")
    assert coordinator.get("nobody") is None


async def test_bridge_info_keeps_versions_only(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await publish(
        hass,
        f"{Z2M}/bridge/info",
        {"version": "2.6.3", "config": {"advanced": {"network_key": [1, 2]}}},
    )
    assert entry.runtime_data.coordinator.bridge_info == {Z2M: {"version": "2.6.3"}}


async def test_zigbee2mqtt_thermostat_among_other_devices(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await publish_bridge(
        hass,
        [
            {"friendly_name": "Coordinator", "type": "Coordinator", "ieee_address": "0x00"},
            {"friendly_name": "Some valve", "model_id": "eTRV0100", "ieee_address": "0x01"},
            z2m_descriptor("hall/heater", "0x02"),
        ],
        prefix=Z2M,
    )
    assert list(entry.runtime_data.coordinator.thermostats) == ["0x02"]
    assert state_of(hass, "sensor.hall_heater_temperature") == "19.5"
    assert hass.states.get("sensor.some_valve_temperature") is None


async def test_a_thermostat_moved_to_zigbee2mqtt_keeps_its_entities(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await publish_bridge(hass, [descriptor("Thermostat A1", "dev-a1", "0xA1")])
    registry = er.async_get(hass)
    before = registry.async_get(f"sensor.{A1}_energy")
    assert before is not None and before.unique_id == "dev-a1_energy"

    # Re-paired: the Tuya bridge no longer lists it, Zigbee2MQTT does, by IEEE address only.
    await publish(hass, f"{TUYA}/bridge/devices", [])
    assert state_of(hass, f"sensor.{A1}_energy") == STATE_UNAVAILABLE
    await publish_bridge(
        hass,
        [z2m_descriptor("heater", "0xa1")],
        {"heater": {**STATE, "energy": 101.0}},
        prefix=Z2M,
    )
    assert state_of(hass, f"sensor.{A1}_energy") == "101.0"
    assert entry.runtime_data.coordinator.thermostats["dev-a1"].prefix == Z2M
    assert hass.states.get("sensor.heater_energy") is None


async def test_read_only(hass: HomeAssistant, fleet: MockConfigEntry, mqtt_mock: Any) -> None:
    with pytest.raises(ServiceValidationError) as refused:
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": f"climate.{A1}", "hvac_mode": "heat"},
            blocking=True,
        )
    assert refused.value.translation_key == "no_write_route"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": f"climate.{A1}", "temperature": 21},
            blocking=True,
        )
    mqtt_mock.async_publish.assert_not_called()


async def test_entities_come_back_after_a_restart(
    hass: HomeAssistant, fleet: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_reload(fleet.entry_id)
    await hass.async_block_till_done()
    # Known to the registry, so present at once, and unavailable until the bridge speaks again.
    assert state_of(hass, f"climate.{A1}") == STATE_UNAVAILABLE
    assert state_of(hass, f"sensor.{A1}_energy") == STATE_UNAVAILABLE
    assert state_of(hass, f"binary_sensor.{A1}_heating") == STATE_UNAVAILABLE
    await publish_bridge(hass, [descriptor("Thermostat A1", "dev-a1")])
    assert state_of(hass, f"sensor.{A1}_energy") == "100.5"
    assert len(er.async_entries_for_config_entry(er.async_get(hass), fleet.entry_id)) == 4 * 11


async def test_unusable_entries_of_the_device_list_are_skipped(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    nameless = descriptor("", "dev-x")
    no_identity = {"friendly_name": "y", "tuya": {"product_id": "fu1bfwza"}}
    await publish_bridge(hass, [descriptor("Thermostat A1", "dev-a1")])
    await publish(
        hass,
        f"{TUYA}/bridge/devices",
        [1, nameless, no_identity, descriptor("Thermostat A1", "dev-a1")],
    )
    assert list(entry.runtime_data.coordinator.thermostats) == ["dev-a1"]
