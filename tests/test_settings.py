"""Settings a version-6 bridge opens: further presets, child lock, window detection, calibration,
holiday setpoint. Each is offered only where the bridge opens it, per thermostat and per room.

Everything runs on the mocked broker; no test sends anything anywhere.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_pilot_wire.const import CONF_MQTT_PREFIXES, DOMAIN
from custom_components.tuya_pilot_wire.diagnostics import async_get_config_entry_diagnostics

from .conftest import STATE, TUYA, Z2M, descriptor, fire, publish_bridge
from .test_writes import FLEET, climate_call, published, run

ROOM = "climate.room_a"
B1 = "climate.thermostat_b1"
ROOM_LOCK = "switch.room_a_child_lock"
ROOM_WINDOW = "switch.room_a_open_window_detection"
ROOM_HOLIDAY = "number.room_a_holiday_setpoint"
ROOM_CALIBRATION = "number.room_a_temperature_calibration"
A1_LOCK = "switch.thermostat_a1_child_lock"
A1_WINDOW = "switch.thermostat_a1_open_window_detection"
A1_CALIBRATION = "number.thermostat_a1_temperature_calibration"
A1_HOLIDAY = "number.thermostat_a1_holiday_setpoint"
DISAGREE = "binary_sensor.room_a_thermostats_disagree"
SETTINGS = [
    "child_lock",
    "window_detection",
    "local_temperature_calibration",
    "holiday_temperature",
]
ALL_KEYS = ["current_heating_setpoint", "preset", *SETTINGS]
ALL_PRESETS = ["manual", "program", "holiday", "antifrost", "eco"]
ROOM_MEMBERS = ["Thermostat A1", "Thermostat A2"]
CALIBRATED = {**STATE, "local_temperature_calibration": -2}


async def info_v6(
    hass: HomeAssistant,
    devices: list[str],
    keys: list[str] | None = None,
    presets: Any = None,
    prefix: str = TUYA,
    read_only: bool = False,
    **writes: Any,
) -> None:
    """`bridge/info` of a version-6 bridge."""
    announced: dict[str, Any] = {
        "enabled": True,
        "keys": ALL_KEYS if keys is None else keys,
        "presets": ["manual", "program"] if presets is None else presets,
        "settings": [],
        "devices": devices,
        "device": devices[0] if devices else None,
        **writes,
    }
    fire(
        hass,
        f"{prefix}/bridge/info",
        {"version": "0.5.0", "contract": 7, "read_only": read_only, "writes": announced},
    )
    await hass.async_block_till_done()


async def publish(hass: HomeAssistant, name: str, prefix: str = TUYA, **changes: Any) -> None:
    fire(hass, f"{prefix}/{name}", {**CALIBRATED, **changes})
    await hass.async_block_till_done()


def commands(mqtt_mock: Any) -> list[tuple[str, dict[str, Any]]]:
    """What was published, without the transactions."""
    return [
        (
            topic.removeprefix(f"{TUYA}/").removesuffix("/set"),
            {k: v for k, v in c.items() if k != "transaction"},
        )
        for topic, c in published(mqtt_mock)
    ]


def features(hass: HomeAssistant, entity_id: str) -> ClimateEntityFeature:
    return ClimateEntityFeature(hass.states.get(entity_id).attributes["supported_features"])


async def create_room(hass: HomeAssistant, members: list[str]) -> None:
    await hass.services.async_call(
        DOMAIN,
        "create_room",
        {"name": "Room A", "thermostats": members},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()


@pytest.fixture
async def room(hass: HomeAssistant, fleet: MockConfigEntry) -> MockConfigEntry:
    """Room "Room A" with A1 and A2, each reporting a calibration; B1 and B2 outside any room."""
    await create_room(hass, ROOM_MEMBERS)
    await publish_bridge(hass, FLEET, {d["friendly_name"]: CALIBRATED for d in FLEET})
    return fleet


@pytest.fixture
async def opened(hass: HomeAssistant, room: MockConfigEntry) -> MockConfigEntry:
    """Every key, and every preset, open for the room's two thermostats and for B1."""
    await info_v6(hass, [*ROOM_MEMBERS, "Thermostat B1"], presets=ALL_PRESETS)
    return room


# -- presets -------------------------------------------------------------------------------------


async def test_the_presets_of_a_version_6_bridge(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    state = hass.states.get(ROOM)
    # In the Companion's order, whatever the bridge's.
    assert state.attributes["preset_modes"] == ["program", "manual", "eco", "holiday", "antifrost"]
    assert state.attributes["preset_mode"] == "manual"
    await run(hass, mqtt_mock, climate_call(hass, "set_preset_mode", ROOM, preset_mode="holiday"))
    assert commands(mqtt_mock) == [
        ("Thermostat A1", {"preset": "holiday"}),
        ("Thermostat A2", {"preset": "holiday"}),
    ]
    # Nothing moves until the devices are read back in the new mode.
    assert hass.states.get(ROOM).attributes["preset_mode"] == "manual"
    await publish(hass, "Thermostat A1", preset="holiday")
    await publish(hass, "Thermostat A2", preset="holiday")
    assert hass.states.get(ROOM).attributes["preset_mode"] == "holiday"


async def test_only_the_presets_open_are_offered(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    # Unknown values and non-strings in the list are ignored.
    await info_v6(hass, ROOM_MEMBERS, presets=["manual", "program", "eco", "boost", 4])
    assert hass.states.get(ROOM).attributes["preset_modes"] == ["program", "manual", "eco"]
    # A reported preset that is not open is not shown as chosen; the attribute still says it.
    await publish(hass, "Thermostat A1", preset="holiday")
    await publish(hass, "Thermostat A2", preset="holiday")
    state = hass.states.get(ROOM)
    assert state.attributes["preset_mode"] is None
    assert state.attributes["preset"] == "holiday"
    coordinator = room.runtime_data.coordinator
    with pytest.raises(ServiceValidationError) as refused:
        await coordinator.async_set_many(["dev-a1", "dev-a2"], "preset", "holiday")
    assert refused.value.translation_key == "preset_closed"
    assert refused.value.translation_placeholders == {
        "preset": "holiday",
        "thermostats": "Thermostat A1, Thermostat A2",
    }
    mqtt_mock.async_publish.assert_not_called()


async def test_a_room_offers_the_presets_open_on_every_member(
    hass: HomeAssistant, fleet: MockConfigEntry, mqtt_mock: Any
) -> None:
    """A1 behind one bridge, Z1 behind another: the room offers what both open."""
    await publish_bridge(hass, [descriptor("Thermostat Z1", "dev-z1")], prefix=Z2M)
    await create_room(hass, ["Thermostat A1", "Thermostat Z1"])
    await publish_bridge(hass, FLEET)
    await publish_bridge(hass, [descriptor("Thermostat Z1", "dev-z1")], prefix=Z2M)
    await info_v6(hass, ["Thermostat A1"], presets=["manual", "program", "eco", "holiday"])
    await info_v6(hass, ["Thermostat Z1"], presets=["program", "holiday", "manual"], prefix=Z2M)
    assert hass.states.get(ROOM).attributes["preset_modes"] == ["program", "manual", "holiday"]
    # Home Assistant refuses a preset not offered; the Companion names who does not open it.
    with pytest.raises(ServiceValidationError):
        await climate_call(hass, "set_preset_mode", ROOM, preset_mode="eco")
    with pytest.raises(ServiceValidationError) as refused:
        await fleet.runtime_data.coordinator.async_set_many(["dev-a1", "dev-z1"], "preset", "eco")
    assert refused.value.translation_placeholders["thermostats"] == "Thermostat Z1"
    # No preset in common: no preset control at all.
    await info_v6(hass, ["Thermostat Z1"], presets=[], prefix=Z2M)
    assert not features(hass, ROOM) & ClimateEntityFeature.PRESET_MODE
    assert "preset_modes" not in hass.states.get(ROOM).attributes
    mqtt_mock.async_publish.assert_not_called()


async def test_a_malformed_preset_list_opens_none(
    hass: HomeAssistant, room: MockConfigEntry
) -> None:
    await info_v6(hass, ROOM_MEMBERS, presets="manual")
    assert features(hass, ROOM) == ClimateEntityFeature.TARGET_TEMPERATURE
    # A version-5 bridge, which has no list: `manual` and `program`.
    fire(
        hass,
        f"{TUYA}/bridge/info",
        {
            "contract": 5,
            "read_only": False,
            "writes": {"keys": ["preset"], "devices": ROOM_MEMBERS},
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(ROOM).attributes["preset_modes"] == ["program", "manual"]


async def test_a_trial_is_never_offered(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    await info_v6(
        hass,
        ROOM_MEMBERS,
        keys=["current_heating_setpoint", "preset"],
        trial={"setting": "child_lock", "key": "child_lock", "device": "Thermostat A1"},
        refused={"window_detection": "candidate route: opens once the library records its trial"},
    )
    await info_v6(
        hass,
        ROOM_MEMBERS,
        keys=["current_heating_setpoint", "preset"],
        trial={
            "setting": "preset_eco",
            "key": "preset",
            "preset": "eco",
            "device": "Thermostat A1",
        },
    )
    assert hass.states.async_all("switch") == []
    assert [s.entity_id for s in hass.states.async_all("number")] == [
        "number.thermostat_a1_manual_setpoint",
        "number.thermostat_a2_manual_setpoint",
    ]
    assert hass.states.get(ROOM).attributes["preset_modes"] == ["program", "manual"]
    with pytest.raises(ServiceValidationError) as refused:
        await room.runtime_data.coordinator.async_set_many(["dev-a1"], "child_lock", "UNLOCK")
    assert refused.value.translation_key == "write_closed"
    mqtt_mock.async_publish.assert_not_called()


# -- switches ------------------------------------------------------------------------------------


async def test_no_switch_until_the_bridge_opens(hass: HomeAssistant, room: MockConfigEntry) -> None:
    assert hass.states.async_all("switch") == []
    await info_v6(hass, ROOM_MEMBERS, keys=["child_lock"], read_only=True, closed="disabled")
    assert hass.states.async_all("switch") == []
    # Open for one member: that thermostat's switch, not the room's.
    await info_v6(hass, ["Thermostat A1"], keys=["child_lock"])
    assert [s.entity_id for s in hass.states.async_all("switch")] == [A1_LOCK]


async def test_a_thermostat_switch(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    lock = hass.states.get(A1_LOCK)
    assert lock.state == STATE_ON
    assert hass.states.get(A1_WINDOW).state == STATE_OFF
    entry = er.async_get(hass).async_get(A1_LOCK)
    assert entry.unique_id == "dev-a1_child_lock"
    assert entry.entity_category == "config"
    assert er.async_get(hass).async_get(A1_WINDOW).unique_id == "dev-a1_window_detection"
    await run(
        hass,
        mqtt_mock,
        hass.services.async_call("switch", "turn_off", {"entity_id": A1_LOCK}, blocking=True),
    )
    await run(
        hass,
        mqtt_mock,
        hass.services.async_call("switch", "turn_on", {"entity_id": A1_WINDOW}, blocking=True),
    )
    assert commands(mqtt_mock) == [
        ("Thermostat A1", {"child_lock": "UNLOCK"}),
        ("Thermostat A1", {"window_detection": "ON"}),
    ]
    # Confirmed, and still what the device last said.
    assert hass.states.get(A1_LOCK).state == STATE_ON
    await publish(hass, "Thermostat A1", child_lock="UNLOCK", window_detection="ON")
    assert hass.states.get(A1_LOCK).state == STATE_OFF
    assert hass.states.get(A1_WINDOW).state == STATE_ON
    # Not reported: unavailable. Closed: unavailable.
    await publish(hass, "Thermostat A1", child_lock=None)
    assert hass.states.get(A1_LOCK).state == STATE_UNAVAILABLE
    await info_v6(hass, ROOM_MEMBERS, keys=["preset"])
    assert hass.states.get(A1_WINDOW).state == STATE_UNAVAILABLE


async def test_a_refused_switch_is_the_bridges_words(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    with pytest.raises(HomeAssistantError) as refused:
        await run(
            hass,
            mqtt_mock,
            hass.services.async_call("switch", "turn_off", {"entity_id": A1_LOCK}, blocking=True),
            {"Thermostat A1": lambda name, c: {"status": "error", "error": "not confirmed"}},
        )
    assert refused.value.translation_key == "set_refused"


async def test_a_room_switch_goes_to_each_member(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    assert hass.states.get(ROOM_LOCK).state == STATE_ON
    assert er.async_get(hass).async_get(ROOM_LOCK).unique_id.startswith("room_")
    await run(
        hass,
        mqtt_mock,
        hass.services.async_call("switch", "turn_off", {"entity_id": ROOM_LOCK}, blocking=True),
    )
    assert commands(mqtt_mock) == [
        ("Thermostat A1", {"child_lock": "UNLOCK"}),
        ("Thermostat A2", {"child_lock": "UNLOCK"}),
    ]
    assert hass.states.get(ROOM_LOCK).state == STATE_ON
    # One member confirmed so far: the members disagree, the room has no value, and says why.
    await publish(hass, "Thermostat A1", child_lock="UNLOCK")
    assert hass.states.get(ROOM_LOCK).state == STATE_UNAVAILABLE
    assert hass.states.get(DISAGREE).state == STATE_ON
    assert hass.states.get(DISAGREE).attributes["differing"] == ["child_lock"]
    assert hass.states.get(ROOM).attributes["differing"] == ["child_lock"]
    await publish(hass, "Thermostat A2", child_lock="UNLOCK")
    assert hass.states.get(ROOM_LOCK).state == STATE_OFF
    assert hass.states.get(DISAGREE).state == STATE_OFF
    # A member that does not report it: unknown, not a disagreement.
    await publish(hass, "Thermostat A2", child_lock=None)
    assert hass.states.get(ROOM_LOCK).state == STATE_UNAVAILABLE
    assert hass.states.get(DISAGREE).state == STATE_OFF


async def test_a_room_switch_needs_every_member_open(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    await info_v6(hass, ["Thermostat A1"])
    assert hass.states.get(ROOM_LOCK).state == STATE_UNAVAILABLE
    assert hass.states.get(A1_LOCK).state == STATE_ON
    # A difference in a setting no room control is open for is not named.
    await publish(hass, "Thermostat A2", child_lock="UNLOCK")
    assert hass.states.get(DISAGREE).state == STATE_OFF
    entity = hass.data["switch"].get_entity(ROOM_LOCK)
    with pytest.raises(ServiceValidationError) as refused:
        await entity.async_turn_on()
    assert refused.value.translation_key == "write_closed"
    assert refused.value.translation_placeholders == {
        "key": "child_lock",
        "thermostats": "Thermostat A2",
    }
    mqtt_mock.async_publish.assert_not_called()


async def test_a_member_not_confirmed_is_named(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    with pytest.raises(HomeAssistantError) as failed:
        await run(
            hass,
            mqtt_mock,
            hass.services.async_call(
                "switch", "turn_on", {"entity_id": ROOM_WINDOW}, blocking=True
            ),
            {"Thermostat A2": lambda name, c: {"status": "error", "error": "offline"}},
        )
    assert failed.value.translation_placeholders == {
        "failed": "Thermostat A2 (offline)",
        "confirmed": "Thermostat A1",
    }
    assert len(published(mqtt_mock)) == 2


# -- numbers -------------------------------------------------------------------------------------


async def test_the_calibration_number(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    state = hass.states.get(A1_CALIBRATION)
    assert state.state == "-2.0"
    assert (state.attributes["min"], state.attributes["max"], state.attributes["step"]) == (
        -9.0,
        9.0,
        1.0,
    )
    assert state.attributes["unit_of_measurement"] == "°C"
    entry = er.async_get(hass).async_get(A1_CALIBRATION)
    assert entry.unique_id == "dev-a1_local_temperature_calibration"
    assert entry.entity_category == "config"
    await run(
        hass,
        mqtt_mock,
        hass.services.async_call(
            "number", "set_value", {"entity_id": A1_CALIBRATION, "value": 3}, blocking=True
        ),
    )
    # Sent as an integer, as the bridge takes it.
    raw = mqtt_mock.async_publish.mock_calls[-1].args[1]
    assert '"local_temperature_calibration": 3,' in raw
    assert hass.states.get(A1_CALIBRATION).state == "-2.0"


async def test_the_holiday_setpoint_of_a_room(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    state = hass.states.get(ROOM_HOLIDAY)
    assert state.state == "5.0"
    assert (state.attributes["min"], state.attributes["max"], state.attributes["step"]) == (
        5.0,
        30.0,
        0.5,
    )
    assert er.async_get(hass).async_get(A1_HOLIDAY).unique_id == "dev-a1_holiday_temperature"
    assert hass.states.get(ROOM_CALIBRATION).state == "-2.0"
    # Whatever the preset: the holiday setpoint does not depend on it.
    await publish(hass, "Thermostat A2", preset="program")
    await run(
        hass,
        mqtt_mock,
        hass.services.async_call(
            "number", "set_value", {"entity_id": ROOM_HOLIDAY, "value": 12.5}, blocking=True
        ),
    )
    assert commands(mqtt_mock) == [
        ("Thermostat A1", {"holiday_temperature": 12.5}),
        ("Thermostat A2", {"holiday_temperature": 12.5}),
    ]
    await publish(hass, "Thermostat A1", holiday_temperature=12.5)
    assert hass.states.get(ROOM_HOLIDAY).state == STATE_UNAVAILABLE
    assert hass.states.get(DISAGREE).attributes["differing"] == ["preset", "holiday_temperature"]


@pytest.mark.parametrize(
    ("set_key", "value", "code"),
    [
        ("local_temperature_calibration", 10, "value_out_of_bounds"),
        ("local_temperature_calibration", -9.5, "value_out_of_bounds"),
        ("local_temperature_calibration", 1.5, "value_out_of_bounds"),
        ("holiday_temperature", 30.5, "value_out_of_bounds"),
        ("holiday_temperature", 4.5, "value_out_of_bounds"),
        ("holiday_temperature", 12.3, "value_out_of_bounds"),
        ("child_lock", "YES", "value_not_allowed"),
        ("child_lock", True, "value_not_allowed"),
        ("window_detection", "on", "value_not_allowed"),
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


async def test_a_number_out_of_bounds_through_the_entity(
    hass: HomeAssistant, opened: MockConfigEntry, mqtt_mock: Any
) -> None:
    entity = hass.data["number"].get_entity(ROOM_CALIBRATION)
    with pytest.raises(ServiceValidationError) as refused:
        await entity.async_set_native_value(0.5)
    assert refused.value.translation_placeholders == {"low": "-9.0", "high": "9.0", "step": "1.0"}
    mqtt_mock.async_publish.assert_not_called()


# -- registry and diagnostics --------------------------------------------------------------------


async def test_settings_come_back_after_a_reload(
    hass: HomeAssistant, opened: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    # A registry entry of a room that no longer exists is left alone.
    registry.async_get_or_create("switch", DOMAIN, "room_gone_child_lock", config_entry=opened)
    assert await hass.config_entries.async_reload(opened.entry_id)
    await hass.async_block_till_done()
    for entity_id in (ROOM_LOCK, A1_LOCK, ROOM_HOLIDAY, A1_CALIBRATION):
        assert hass.states.get(entity_id).state != STATE_UNAVAILABLE, entity_id
    await info_v6(hass, [], read_only=True, closed="writes are disabled")
    for entity_id in (ROOM_LOCK, A1_LOCK, ROOM_HOLIDAY, A1_CALIBRATION):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE, entity_id
    assert hass.states.get("switch.room_gone_child_lock") is None


async def test_diagnostics_of_a_version_6_bridge(
    hass: HomeAssistant, opened: MockConfigEntry
) -> None:
    await info_v6(
        hass,
        [*ROOM_MEMBERS, "Thermostat B1"],
        keys=["current_heating_setpoint", "preset", "child_lock"],
        presets=["manual", "program", "eco"],
        settings=["child_lock", "preset_eco"],
        refused={"window_detection": "candidate route, asked for Thermostat B2"},
        trial={
            "setting": "holiday_temperature",
            "key": "holiday_temperature",
            "device": "Thermostat B2",
            "closed": "Thermostat B2 is not designated",
        },
    )
    diagnostics = await async_get_config_entry_diagnostics(hass, opened)
    text = json.dumps(diagnostics)
    assert "Thermostat " not in text
    bridge = diagnostics["bridges"][TUYA]
    writes = bridge["info"]["writes"]
    assert writes["presets"] == ["manual", "program", "eco"]
    assert writes["settings"] == ["child_lock", "preset_eco"]
    assert writes["refused"] == {"window_detection": "candidate route, asked for thermostat_4"}
    assert writes["trial"] == {
        "setting": "holiday_temperature",
        "key": "holiday_temperature",
        "device": "thermostat_4",
        "closed": "thermostat_4 is not designated",
    }
    assert bridge["open_keys"]["thermostat_1"] == [
        "child_lock",
        "current_heating_setpoint",
        "preset",
    ]
    assert bridge["open_presets"] == {
        ref: ["program", "manual", "eco"]
        for ref in ("thermostat_1", "thermostat_2", "thermostat_3")
    }
    assert diagnostics["set_choices"] == {
        "child_lock": ["LOCK", "UNLOCK"],
        "window_detection": ["ON", "OFF"],
    }
    assert diagnostics["set_bounds"]["local_temperature_calibration"] == [-9.0, 9.0, 1.0]
    (room,) = diagnostics["rooms"]
    assert (room["child_lock"], room["window_detection"]) == (True, False)
    assert (room["local_temperature_calibration"], room["holiday_temperature"]) == (-2.0, 5.0)
    # A trial in a shape this version does not know is still stripped of names.
    await info_v6(hass, ROOM_MEMBERS, trial="Thermostat A1", refused=["Thermostat A2"])
    text = json.dumps(await async_get_config_entry_diagnostics(hass, opened))
    assert "Thermostat A1" not in text
    assert "thermostat_1" in text


async def test_an_entry_reading_one_prefix(hass: HomeAssistant, mqtt_mock: Any) -> None:
    """The settings' setup with no thermostat and no room creates nothing."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_MQTT_PREFIXES: [TUYA]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await info_v6(hass, ["Thermostat A1"])
    assert hass.states.async_all("switch") == []
