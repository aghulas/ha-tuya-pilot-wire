"""The one write under trial: the manual setpoint of the single designated thermostat.

Everything here runs on the mocked broker; no test sends anything anywhere.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_pilot_wire.const import CONF_TRIAL_THERMOSTAT, OPEN_SET_KEYS
from custom_components.tuya_pilot_wire.diagnostics import async_get_config_entry_diagnostics

from .conftest import STATE, TUYA, descriptor, fire, publish_bridge

NUMBER = "number.thermostat_a1_manual_setpoint"
SET_TOPIC = f"{TUYA}/Thermostat A1/set"


async def designate(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> None:
    """Choose the trial thermostat through the options flow (the entry reloads)."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "trial"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TRIAL_THERMOSTAT: key}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def bridge_info(hass: HomeAssistant, read_only: bool) -> None:
    fire(hass, f"{TUYA}/bridge/info", {"version": "0.2.0", "read_only": read_only})
    await hass.async_block_till_done()


@pytest.fixture
async def trial(hass: HomeAssistant, fleet: MockConfigEntry) -> MockConfigEntry:
    """A1 designated for the trial, behind a bridge that accepts writes."""
    await designate(hass, fleet, "dev-a1")
    await bridge_info(hass, read_only=False)
    return fleet


def published(mqtt_mock: Any) -> list[tuple[str, dict[str, Any]]]:
    return [(call.args[0], json.loads(call.args[1])) for call in mqtt_mock.async_publish.mock_calls]


async def set_value(hass: HomeAssistant, value: float) -> None:
    await hass.services.async_call(
        "number", "set_value", {"entity_id": NUMBER, "value": value}, blocking=True
    )


async def answer(hass: HomeAssistant, mqtt_mock: Any, **response: Any) -> None:
    """Answer the last published command as the bridge would."""
    for _ in range(50):
        if mqtt_mock.async_publish.mock_calls:
            break
        await asyncio.sleep(0)
    _, command = published(mqtt_mock)[-1]
    fire(
        hass,
        f"{TUYA}/bridge/response/device/set",
        {"transaction": command["transaction"], **response},
    )


def test_no_key_is_open_for_every_thermostat() -> None:
    assert frozenset() == OPEN_SET_KEYS


async def test_closed_by_default(hass: HomeAssistant, fleet: MockConfigEntry) -> None:
    await bridge_info(hass, read_only=False)
    assert hass.states.async_all("number") == []
    coordinator = fleet.runtime_data.coordinator
    assert not coordinator.supports_set("dev-a1", "current_heating_setpoint")
    with pytest.raises(ServiceValidationError) as refused:
        await coordinator.async_set("dev-a1", "current_heating_setpoint", 20.0)
    assert refused.value.translation_key == "no_write_route"


async def test_a_read_only_bridge_keeps_it_closed(
    hass: HomeAssistant, fleet: MockConfigEntry, mqtt_mock: Any
) -> None:
    await designate(hass, fleet, "dev-a1")
    # The bridge has not said, then says it is read only: no control either way.
    assert hass.states.get(NUMBER) is None
    await bridge_info(hass, read_only=True)
    assert hass.states.get(NUMBER) is None
    with pytest.raises(ServiceValidationError):
        await fleet.runtime_data.coordinator.async_set("dev-a1", "current_heating_setpoint", 20.0)
    mqtt_mock.async_publish.assert_not_called()


async def test_only_the_designated_thermostat(hass: HomeAssistant, trial: MockConfigEntry) -> None:
    state = hass.states.get(NUMBER)
    assert state is not None and state.state == "20.0"
    assert (state.attributes["min"], state.attributes["max"], state.attributes["step"]) == (
        5.0,
        40.0,
        0.5,
    )
    assert [s.entity_id for s in hass.states.async_all("number")] == [NUMBER]
    coordinator = trial.runtime_data.coordinator
    assert not coordinator.supports_set("dev-a2", "current_heating_setpoint")
    assert not coordinator.supports_set("dev-a1", "system_mode")
    assert not coordinator.supports_set("nobody", "current_heating_setpoint")
    diagnostics = await async_get_config_entry_diagnostics(hass, trial)
    assert diagnostics["trial_thermostat"] == "thermostat_1"


async def test_a_write_changes_nothing_until_the_device_confirms(
    hass: HomeAssistant, trial: MockConfigEntry, mqtt_mock: Any
) -> None:
    call = hass.async_create_task(set_value(hass, 20.5))
    await answer(hass, mqtt_mock, status="ok", data={"current_heating_setpoint": 20.5})
    await call
    (topic, command) = published(mqtt_mock)[-1]
    assert topic == SET_TOPIC
    assert command == {"current_heating_setpoint": 20.5, "transaction": command["transaction"]}
    assert len(published(mqtt_mock)) == 1
    # Accepted by the bridge, and still the old value: the state topic has not spoken.
    assert hass.states.get(NUMBER).state == "20.0"
    fire(hass, f"{TUYA}/Thermostat A1", {**STATE, "current_heating_setpoint": 20.5})
    await hass.async_block_till_done()
    assert hass.states.get(NUMBER).state == "20.5"


async def test_a_refusal_is_reported(
    hass: HomeAssistant, trial: MockConfigEntry, mqtt_mock: Any
) -> None:
    call = hass.async_create_task(set_value(hass, 21.0))
    # A response to someone else's command, and a malformed one, are not ours.
    fire(hass, f"{TUYA}/bridge/response/device/set", {"status": "ok", "transaction": "other"})
    fire(hass, f"{TUYA}/bridge/response/device/set", "not json")
    await answer(hass, mqtt_mock, status="error", error="the device did not take the value")
    with pytest.raises(HomeAssistantError) as refused:
        await call
    assert refused.value.translation_key == "set_refused"
    assert refused.value.translation_placeholders == {"error": "the device did not take the value"}
    assert hass.states.get(NUMBER).state == "20.0"
    assert trial.runtime_data.coordinator._pending == {}


async def test_no_answer_is_an_error(
    hass: HomeAssistant, trial: MockConfigEntry, mqtt_mock: Any
) -> None:
    with (
        patch("custom_components.tuya_pilot_wire.coordinator.SET_TIMEOUT", 0.01),
        pytest.raises(HomeAssistantError) as silent,
    ):
        await set_value(hass, 21.0)
    assert silent.value.translation_key == "set_no_answer"
    assert hass.states.get(NUMBER).state == "20.0"
    assert trial.runtime_data.coordinator._pending == {}


@pytest.mark.parametrize("value", [4.5, 40.5, 20.3])
async def test_values_are_checked_before_anything_is_sent(
    hass: HomeAssistant, trial: MockConfigEntry, mqtt_mock: Any, value: float
) -> None:
    with pytest.raises(ServiceValidationError) as refused:
        await trial.runtime_data.coordinator.async_set("dev-a1", "current_heating_setpoint", value)
    assert refused.value.translation_key == "value_out_of_bounds"
    mqtt_mock.async_publish.assert_not_called()


async def test_nothing_is_sent_to_an_unavailable_thermostat(
    hass: HomeAssistant, trial: MockConfigEntry, mqtt_mock: Any
) -> None:
    fire(hass, f"{TUYA}/Thermostat A1/availability", {"state": "offline"})
    await hass.async_block_till_done()
    assert hass.states.get(NUMBER).state == STATE_UNAVAILABLE
    with pytest.raises(ServiceValidationError) as refused:
        await trial.runtime_data.coordinator.async_set("dev-a1", "current_heating_setpoint", 20.5)
    assert refused.value.translation_key == "thermostat_unavailable"
    mqtt_mock.async_publish.assert_not_called()


async def test_the_control_follows_the_bridge_and_the_setpoint(
    hass: HomeAssistant, trial: MockConfigEntry
) -> None:
    fire(hass, f"{TUYA}/Thermostat A1", {"local_temperature": 19.0})
    await hass.async_block_till_done()
    assert hass.states.get(NUMBER).state == STATE_UNAVAILABLE
    fire(hass, f"{TUYA}/Thermostat A1", STATE)
    await bridge_info(hass, read_only=True)
    assert hass.states.get(NUMBER).state == STATE_UNAVAILABLE


async def test_closing_the_trial_removes_the_control(
    hass: HomeAssistant, trial: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    assert registry.async_get(NUMBER) is not None
    # The form proposes the current choice, and a thermostat its bridge no longer lists.
    fire(hass, f"{TUYA}/bridge/devices", [descriptor("Thermostat A2", "dev-a2")])
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(trial.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "trial"}
    )
    offered = result["data_schema"].schema[CONF_TRIAL_THERMOSTAT].config["options"]
    assert [option["value"] for option in offered] == ["none", "dev-a2", "dev-a1"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TRIAL_THERMOSTAT: "none"}
    )
    await hass.async_block_till_done()
    assert trial.options[CONF_TRIAL_THERMOSTAT] is None
    assert registry.async_get(NUMBER) is None
    assert trial.runtime_data.coordinator.trial_thermostat is None
    diagnostics = await async_get_config_entry_diagnostics(hass, trial)
    assert diagnostics["trial_thermostat"] is None


async def test_moving_the_trial_moves_the_control(
    hass: HomeAssistant, trial: MockConfigEntry
) -> None:
    await designate(hass, trial, "dev-a2")
    await publish_bridge(
        hass, [descriptor(f"Thermostat {n}", f"dev-{n.lower()}") for n in ("A1", "A2", "B1", "B2")]
    )
    await bridge_info(hass, read_only=False)
    assert [s.entity_id for s in hass.states.async_all("number")] == [
        "number.thermostat_a2_manual_setpoint"
    ]
    assert er.async_get(hass).async_get(NUMBER) is None
