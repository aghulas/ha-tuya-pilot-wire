"""Writes: preset and manual setpoint, on room and thermostat climates and the setpoint number.

A write is offered only where the bridge announces it open (`bridge/info.writes`, contract
version 5). Everything here runs on the mocked broker; no test sends anything anywhere.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_pilot_wire.const import (
    CONF_MQTT_PREFIXES,
    DOMAIN,
    LEGACY_CONF_TRIAL_THERMOSTAT,
    SET_KEYS,
)
from custom_components.tuya_pilot_wire.diagnostics import async_get_config_entry_diagnostics

from .conftest import STATE, TUYA, Z2M, descriptor, fire, publish_bridge

ROOM = "climate.room_a"
B1 = "climate.thermostat_b1"
NUMBER_A1 = "number.thermostat_a1_manual_setpoint"
BOTH = ["current_heating_setpoint", "preset"]
FLEET = [descriptor(f"Thermostat {n}", f"dev-{n.lower()}") for n in ("A1", "A2", "B1", "B2")]
NO_FEATURE = ClimateEntityFeature(0)
ALL_FEATURES = ClimateEntityFeature.PRESET_MODE | ClimateEntityFeature.TARGET_TEMPERATURE

Response = dict[str, Any] | None


async def bridge_info(
    hass: HomeAssistant,
    devices: list[str] | None = None,
    keys: list[str] | None = None,
    read_only: bool = False,
    **writes: Any,
) -> None:
    """`bridge/info` of a version-5 bridge; ``devices=None`` leaves `devices` out."""
    announced: dict[str, Any] = {"enabled": True, "keys": BOTH if keys is None else keys}
    if devices is not None:
        announced["devices"] = devices
    announced.update(writes)
    fire(
        hass,
        f"{TUYA}/bridge/info",
        {"version": "0.3.0", "contract": 5, "read_only": read_only, "writes": announced},
    )
    await hass.async_block_till_done()


async def publish(hass: HomeAssistant, name: str, **changes: Any) -> None:
    fire(hass, f"{TUYA}/{name}", {**STATE, **changes})
    await hass.async_block_till_done()


def published(mqtt_mock: Any) -> list[tuple[str, dict[str, Any]]]:
    return [(call.args[0], json.loads(call.args[1])) for call in mqtt_mock.async_publish.mock_calls]


def ok(name: str, command: dict[str, Any]) -> Response:
    key, value = next((k, v) for k, v in command.items() if k != "transaction")
    return {
        "status": "ok",
        "data": {
            "device": name,
            "results": [{"property": key, "value": value, "confirmed": True}],
        },
    }


async def run(
    hass: HomeAssistant,
    mqtt_mock: Any,
    call: Any,
    answers: dict[str, Callable[[str, dict[str, Any]], Response]] | None = None,
) -> None:
    """Run a service call, answering each command as the bridge would, one after the other.

    ``answers`` maps a bridge name to how it answers (default: written and read back); an answer
    of None is silence.
    """
    task = hass.async_create_task(call)
    handled = 0
    while not task.done():
        commands = published(mqtt_mock)
        for topic, command in commands[handled:]:
            name = topic.removeprefix(f"{TUYA}/").removesuffix("/set")
            response = (answers or {}).get(name, ok)(name, command)
            if response is not None:
                fire(
                    hass,
                    f"{TUYA}/bridge/response/device/set",
                    {**response, "transaction": command["transaction"]},
                )
        handled = len(commands)
        await asyncio.sleep(0)
    await task


def climate_call(hass: HomeAssistant, service: str, entity_id: str, **data: Any) -> Any:
    return hass.services.async_call(
        "climate", service, {"entity_id": entity_id, **data}, blocking=True
    )


@pytest.fixture
async def room(hass: HomeAssistant, fleet: MockConfigEntry) -> MockConfigEntry:
    """Room "Room A" with A1 and A2; B1 and B2 outside any room."""
    await hass.services.async_call(
        DOMAIN,
        "create_room",
        {"name": "Room A", "thermostats": ["Thermostat A1", "Thermostat A2"]},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()
    await publish_bridge(hass, FLEET)
    return fleet


@pytest.fixture
async def opened(hass: HomeAssistant, room: MockConfigEntry) -> MockConfigEntry:
    """The bridge opens both keys for the room's two thermostats and for B1."""
    await bridge_info(hass, ["Thermostat A1", "Thermostat A2", "Thermostat B1"])
    return room


def features(hass: HomeAssistant, entity_id: str) -> ClimateEntityFeature:
    return ClimateEntityFeature(hass.states.get(entity_id).attributes["supported_features"])


# -- what is offered -----------------------------------------------------------------------------


async def test_closed_until_the_bridge_opens(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    assert features(hass, ROOM) == NO_FEATURE
    assert features(hass, B1) == NO_FEATURE
    assert "preset_modes" not in hass.states.get(ROOM).attributes
    assert hass.states.async_all("number") == []
    with pytest.raises(HomeAssistantError):
        await climate_call(hass, "set_preset_mode", ROOM, preset_mode="manual")
    coordinator = room.runtime_data.coordinator
    with pytest.raises(ServiceValidationError) as refused:
        await coordinator.async_set_many(["dev-a1", "dev-a2"], "preset", "manual")
    assert refused.value.translation_key == "write_closed"
    assert refused.value.translation_placeholders == {
        "key": "preset",
        "thermostats": "Thermostat A1, Thermostat A2",
    }
    mqtt_mock.async_publish.assert_not_called()


async def test_a_read_only_bridge_opens_nothing(hass: HomeAssistant, room: MockConfigEntry) -> None:
    await bridge_info(
        hass, ["Thermostat A1", "Thermostat A2"], read_only=True, closed="writes are disabled"
    )
    assert features(hass, ROOM) == NO_FEATURE
    assert hass.states.async_all("number") == []


async def test_a_room_needs_every_member_open(hass: HomeAssistant, room: MockConfigEntry) -> None:
    await bridge_info(hass, ["Thermostat A1"])
    assert features(hass, ROOM) == NO_FEATURE
    # The thermostat opened gets its own setpoint, even inside a room.
    assert [s.entity_id for s in hass.states.async_all("number")] == [NUMBER_A1]


async def test_each_key_is_its_own_feature(hass: HomeAssistant, room: MockConfigEntry) -> None:
    await bridge_info(hass, ["Thermostat A1", "Thermostat A2"], keys=["preset"])
    assert features(hass, ROOM) == ClimateEntityFeature.PRESET_MODE
    assert "temperature" not in hass.states.get(ROOM).attributes
    await bridge_info(hass, ["Thermostat A1", "Thermostat A2"], keys=["current_heating_setpoint"])
    assert features(hass, ROOM) == ClimateEntityFeature.TARGET_TEMPERATURE
    # A key the Companion does not know is never offered, whatever the bridge says.
    await bridge_info(hass, ["Thermostat A1", "Thermostat A2"], keys=["system_mode"])
    assert features(hass, ROOM) == NO_FEATURE


async def test_controls_of_an_opened_room(hass: HomeAssistant, opened: MockConfigEntry) -> None:
    state = hass.states.get(ROOM)
    assert features(hass, ROOM) == ALL_FEATURES
    assert state.attributes["preset_modes"] == ["program", "manual"]
    assert state.attributes["preset_mode"] == "manual"
    assert state.attributes["temperature"] == 20.0
    assert (
        state.attributes["min_temp"],
        state.attributes["max_temp"],
        state.attributes["target_temp_step"],
    ) == (5.0, 30.0, 0.5)
    assert features(hass, B1) == ALL_FEATURES
    assert features(hass, "climate.thermostat_b2") == NO_FEATURE
    # A preset that cannot be chosen here, and members that differ, show no preset.
    await publish(hass, "Thermostat A1", preset="eco")
    await publish(hass, "Thermostat A2", preset="eco")
    assert hass.states.get(ROOM).attributes["preset_mode"] is None
    await publish(hass, "Thermostat A2", preset="program")
    assert hass.states.get(ROOM).attributes["preset_mode"] is None


async def test_a_bridge_that_closes_takes_the_controls_away(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    await bridge_info(
        hass, ["Thermostat A1", "Thermostat A2"], read_only=True, closed="sharing channel offline"
    )
    assert features(hass, ROOM) == NO_FEATURE
    assert hass.states.get(NUMBER_A1).state == STATE_UNAVAILABLE
    with pytest.raises(ServiceValidationError):
        await opened.runtime_data.coordinator.async_set_many(["dev-a1"], "preset", "program")
    # Malformed announcements open nothing either.
    for writes in ({"keys": "preset", "devices": ["Thermostat A1"]}, {"keys": BOTH}):
        fire(hass, f"{TUYA}/bridge/info", {"read_only": False, "writes": writes})
        await hass.async_block_till_done()
        assert features(hass, ROOM) == NO_FEATURE
    fire(hass, f"{TUYA}/bridge/info", {"read_only": False})
    await hass.async_block_till_done()
    assert features(hass, ROOM) == NO_FEATURE
    mqtt_mock.async_publish.assert_not_called()


async def test_a_version_4_bridge_names_one_device(
    hass: HomeAssistant, room: MockConfigEntry
) -> None:
    await bridge_info(hass, keys=["current_heating_setpoint"], device="Thermostat B1")
    assert features(hass, B1) == ClimateEntityFeature.TARGET_TEMPERATURE
    assert features(hass, ROOM) == NO_FEATURE


# -- fan-out -------------------------------------------------------------------------------------


async def test_a_preset_goes_to_each_member_and_waits_for_the_device(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    await run(hass, mqtt_mock, climate_call(hass, "set_preset_mode", ROOM, preset_mode="program"))
    commands = published(mqtt_mock)
    assert [topic for topic, _ in commands] == [
        f"{TUYA}/Thermostat A1/set",
        f"{TUYA}/Thermostat A2/set",
    ]
    assert [{k: v for k, v in c.items() if k != "transaction"} for _, c in commands] == [
        {"preset": "program"},
        {"preset": "program"},
    ]
    assert commands[0][1]["transaction"] != commands[1][1]["transaction"]
    # Confirmed by the bridge, and still the old preset: the state topics have not spoken.
    assert hass.states.get(ROOM).attributes["preset_mode"] == "manual"
    await publish(hass, "Thermostat A1", preset="program")
    await publish(hass, "Thermostat A2", preset="program")
    assert hass.states.get(ROOM).attributes["preset_mode"] == "program"
    assert opened.runtime_data.coordinator._pending == {}


async def test_a_setpoint_goes_to_each_member(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    await run(hass, mqtt_mock, climate_call(hass, "set_temperature", ROOM, temperature=21.5))
    assert [c for _, c in published(mqtt_mock)] == [
        {"current_heating_setpoint": 21.5, "transaction": c["transaction"]}
        for _, c in published(mqtt_mock)
    ]
    assert len(published(mqtt_mock)) == 2
    assert hass.states.get(ROOM).attributes["temperature"] == 20.0


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (lambda name, c: {"status": "error", "error": "channel failure", "data": {}}, "channel"),
        (
            lambda name, c: {
                "status": "ok",
                "data": {"results": [{"property": "preset", "confirmed": False}]},
            },
            "not confirmed",
        ),
        (lambda name, c: {"status": "error", "data": {}}, "no reason given"),
        (lambda name, c: None, "no answer"),
    ],
)
async def test_a_member_not_confirmed_fails_the_call_and_is_named(
    hass: HomeAssistant,
    opened: MockConfigEntry,
    mqtt_mock: Any,
    answer: Callable[[str, dict[str, Any]], Response],
    reason: str,
) -> None:
    with (
        patch("custom_components.tuya_pilot_wire.coordinator.SET_TIMEOUT", 0.05),
        pytest.raises(HomeAssistantError) as failed,
    ):
        await run(
            hass,
            mqtt_mock,
            climate_call(hass, "set_preset_mode", ROOM, preset_mode="program"),
            {"Thermostat A1": answer},
        )
    assert failed.value.translation_key == "set_not_confirmed"
    placeholders = failed.value.translation_placeholders
    assert placeholders["failed"].startswith("Thermostat A1 (")
    assert reason in placeholders["failed"]
    # The other member was still asked, and confirmed.
    assert placeholders["confirmed"] == "Thermostat A2"
    assert len(published(mqtt_mock)) == 2
    assert opened.runtime_data.coordinator._pending == {}


async def test_no_member_confirmed(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    refuse = lambda name, c: {"status": "error", "error": "refused"}  # noqa: E731
    with pytest.raises(HomeAssistantError) as failed:
        await run(
            hass,
            mqtt_mock,
            climate_call(hass, "set_preset_mode", ROOM, preset_mode="manual"),
            {"Thermostat A1": refuse, "Thermostat A2": refuse},
        )
    assert failed.value.translation_placeholders == {
        "failed": "Thermostat A1 (refused); Thermostat A2 (refused)",
        "confirmed": "none",
    }


# -- refused before anything is sent -------------------------------------------------------------


async def test_a_setpoint_needs_every_member_in_manual(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    await publish(hass, "Thermostat A2", preset="program")
    with pytest.raises(ServiceValidationError) as refused:
        await climate_call(hass, "set_temperature", ROOM, temperature=21.0)
    assert refused.value.translation_key == "not_in_manual"
    assert refused.value.translation_placeholders == {"thermostats": "Thermostat A2 (program)"}
    fire(hass, f"{TUYA}/Thermostat A2", {k: v for k, v in STATE.items() if k != "preset"})
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as refused:
        await climate_call(hass, "set_temperature", ROOM, temperature=21.0)
    assert refused.value.translation_placeholders == {"thermostats": "Thermostat A2 (unknown)"}
    mqtt_mock.async_publish.assert_not_called()


async def test_a_member_not_responding_stops_the_call(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    fire(hass, f"{TUYA}/Thermostat A2/availability", {"state": "offline"})
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as refused:
        await climate_call(hass, "set_preset_mode", ROOM, preset_mode="program")
    assert refused.value.translation_key == "thermostat_unavailable"
    assert refused.value.translation_placeholders == {"thermostats": "Thermostat A2"}
    mqtt_mock.async_publish.assert_not_called()


@pytest.mark.parametrize(
    ("set_key", "value", "code"),
    [
        ("current_heating_setpoint", 20.3, "value_out_of_bounds"),
        ("current_heating_setpoint", 30.5, "value_out_of_bounds"),
        ("current_heating_setpoint", 4.5, "value_out_of_bounds"),
        # A version-5 bridge opens `manual` and `program` only.
        ("preset", "eco", "preset_closed"),
        ("preset", "antifrost", "preset_closed"),
        ("preset", "away", "preset_not_writable"),
        ("preset", 3, "preset_not_writable"),
        ("current_heating_setpoint", "20", "value_out_of_bounds"),
        ("current_heating_setpoint", True, "value_out_of_bounds"),
    ],
)
async def test_values_are_checked_before_anything_is_sent(
    hass: HomeAssistant,
    opened: MockConfigEntry,
    mqtt_mock: Any,
    set_key: str,
    value: Any,
    code: str,
) -> None:
    with pytest.raises(ServiceValidationError) as refused:
        await opened.runtime_data.coordinator.async_set_many(["dev-a1", "dev-a2"], set_key, value)
    assert refused.value.translation_key == code
    mqtt_mock.async_publish.assert_not_called()


async def test_what_has_no_route_is_refused(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    with pytest.raises(ServiceValidationError):
        await climate_call(hass, "set_temperature", ROOM, temperature=21.0, hvac_mode="heat")
    entity = hass.data["climate"].get_entity(ROOM)
    for kwargs in ({}, {"temperature": 21.0, "target_temp_low": 18.0}):
        with pytest.raises(ServiceValidationError):
            await entity.async_set_temperature(**kwargs)
    with pytest.raises(ServiceValidationError):
        await entity.async_set_hvac_mode("off")
    with pytest.raises(ServiceValidationError) as refused:
        await opened.runtime_data.coordinator.async_set_many([], "preset", "manual")
    assert refused.value.translation_key == "no_write_route"
    mqtt_mock.async_publish.assert_not_called()


# -- one thermostat ------------------------------------------------------------------------------


async def test_a_thermostat_outside_any_room(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    await run(hass, mqtt_mock, climate_call(hass, "set_temperature", B1, temperature=19.0))
    assert published(mqtt_mock)[-1][0] == f"{TUYA}/Thermostat B1/set"
    # A single thermostat's refusal is the bridge's own words.
    with pytest.raises(HomeAssistantError) as refused:
        await run(
            hass,
            mqtt_mock,
            climate_call(hass, "set_preset_mode", B1, preset_mode="program"),
            {"Thermostat B1": lambda name, c: {"status": "error", "error": "channel offline"}},
        )
    assert refused.value.translation_key == "set_refused"
    assert refused.value.translation_placeholders == {"error": "channel offline"}


async def test_commands_to_one_thermostat_are_spaced(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    """The bridge takes one write per thermostat every 10 s: the second command waits."""
    with patch("custom_components.tuya_pilot_wire.coordinator.MIN_SET_INTERVAL", 0.3):
        start = time.monotonic()
        await run(hass, mqtt_mock, climate_call(hass, "set_preset_mode", B1, preset_mode="manual"))
        first = time.monotonic() - start
        await run(hass, mqtt_mock, climate_call(hass, "set_temperature", B1, temperature=19.0))
        second = time.monotonic() - start
        # Another thermostat does not wait for B1.
        await run(
            hass, mqtt_mock, climate_call(hass, "set_preset_mode", ROOM, preset_mode="manual")
        )
        third = time.monotonic() - start - second
    assert first < 0.3 <= second
    assert third < 0.3
    assert [c for _, c in published(mqtt_mock)][:2] == [
        {"preset": "manual", "transaction": published(mqtt_mock)[0][1]["transaction"]},
        {
            "current_heating_setpoint": 19.0,
            "transaction": published(mqtt_mock)[1][1]["transaction"],
        },
    ]


async def test_the_setpoint_number(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    state = hass.states.get(NUMBER_A1)
    assert state.state == "20.0"
    assert (state.attributes["min"], state.attributes["max"], state.attributes["step"]) == (
        5.0,
        30.0,
        0.5,
    )
    await run(
        hass,
        mqtt_mock,
        hass.services.async_call(
            "number", "set_value", {"entity_id": NUMBER_A1, "value": 20.5}, blocking=True
        ),
    )
    assert published(mqtt_mock)[-1][1]["current_heating_setpoint"] == 20.5
    assert hass.states.get(NUMBER_A1).state == "20.0"
    with (
        patch("custom_components.tuya_pilot_wire.coordinator.SET_TIMEOUT", 0.01),
        pytest.raises(HomeAssistantError) as silent,
    ):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": NUMBER_A1, "value": 21.0}, blocking=True
        )
    assert silent.value.translation_key == "set_no_answer"


async def test_the_number_comes_back_after_a_reload(
    hass: HomeAssistant, opened: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    assert registry.async_get(NUMBER_A1) is not None
    assert await hass.config_entries.async_reload(opened.entry_id)
    await hass.async_block_till_done()
    # Restored from the registry, with the same entity id, and open again from the handed-over
    # bridge info; unavailable once the bridge closes.
    assert hass.states.get(NUMBER_A1).state == "20.0"
    await bridge_info(hass, [], read_only=True)
    assert hass.states.get(NUMBER_A1).state == STATE_UNAVAILABLE
    assert registry.async_get(ROOM).unique_id.startswith("room_")


# -- options and diagnostics ---------------------------------------------------------------------


async def test_the_trial_option_of_0_2_is_migrated(hass: HomeAssistant, mqtt_mock: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Tuya Pilot Wire",
        data={CONF_MQTT_PREFIXES: [Z2M, TUYA]},
        options={LEGACY_CONF_TRIAL_THERMOSTAT: "dev-a1", CONF_MQTT_PREFIXES: [TUYA]},
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 2
    assert dict(entry.options) == {CONF_MQTT_PREFIXES: [TUYA]}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "trial" not in result["menu_options"]


async def test_an_entry_from_a_later_version_is_not_migrated(
    hass: HomeAssistant, mqtt_mock: Any
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_MQTT_PREFIXES: [TUYA]}, version=2, minor_version=1
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)


async def test_diagnostics_name_no_thermostat(hass: HomeAssistant, opened: MockConfigEntry) -> None:
    await bridge_info(
        hass,
        ["Thermostat A1", "Thermostat A2", "Somebody else", 7],
        read_only=True,
        device="Thermostat B1",
        closed="Thermostat A2 is not online for the account",
    )
    diagnostics = await async_get_config_entry_diagnostics(hass, opened)
    text = json.dumps(diagnostics)
    assert "Thermostat " not in text and "Somebody" not in text
    writes = diagnostics["bridges"][TUYA]["info"]["writes"]
    assert writes["devices"] == ["thermostat_1", "thermostat_2", "unknown", "unknown"]
    assert writes["device"] == "thermostat_3"
    assert writes["closed"] == "thermostat_2 is not online for the account"
    assert diagnostics["set_keys"] == sorted(SET_KEYS)
    assert diagnostics["set_presets"] == ["program", "manual", "eco", "holiday", "antifrost"]
    assert diagnostics["bridges"][TUYA]["open_for"] == []
    await bridge_info(hass, ["Thermostat A1", "Thermostat B1"])
    diagnostics = await async_get_config_entry_diagnostics(hass, opened)
    assert diagnostics["bridges"][TUYA]["open_for"] == ["thermostat_1", "thermostat_3"]
    assert diagnostics["bridges"][Z2M]["open_for"] == []
