"""Weekly schedule: read per thermostat and per room, `get_schedule` and `set_schedule`.

Synthetic bridges on the mocked broker (contract version 6). Nothing is sent anywhere.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_pilot_wire import schedule
from custom_components.tuya_pilot_wire.const import DOMAIN

from .conftest import STATE, TUYA, descriptor, fire, publish_bridge

NIGHT = [{"time": "00:00", "temperature": 7.0}]
DAY = [
    {"time": "00:00", "temperature": 7.0},
    {"time": "07:30", "temperature": 19.0},
    {"time": "17:00", "temperature": 7.0},
]
WEEK = {day: NIGHT for day in schedule.DAYS}
FLEET = [descriptor(f"Thermostat {n}", f"dev-{n.lower()}") for n in ("A1", "A2", "B1", "B2")]
ROOM = "climate.room_a"
B1 = "climate.thermostat_b1"
B1_NAME = "Thermostat B1"
OPEN_TO = ["Thermostat A1", "Thermostat A2", "Thermostat B1"]

Response = dict[str, Any] | None


def with_schedule(week: dict[str, Any] | None, at: str = "2026-11-28T10:00:00Z") -> dict[str, Any]:
    tuya: dict[str, Any] = {"mode": "manual", "read": {}}
    if week is not None:
        tuya["schedule"] = week
        tuya["read"]["schedule"] = {"channel": "developer", "at": at}
    return {**STATE, "tuya": tuya}


async def bridge_info(
    hass: HomeAssistant,
    devices: list[str] | None = None,
    requests: list[str] | None = None,
    developer: str = "online",
) -> None:
    """`bridge/info` of a version-6 bridge."""
    fire(
        hass,
        f"{TUYA}/bridge/info",
        {
            "version": "0.4.0",
            "contract": 6,
            "read_only": False,
            "writes": {
                "enabled": True,
                "keys": ["current_heating_setpoint", "preset"],
                "devices": OPEN_TO if devices is None else devices,
                "requests": ["schedule/set"] if requests is None else requests,
            },
            "channels": {"developer": {"enabled": True, "state": developer}},
        },
    )
    await hass.async_block_till_done()


@pytest.fixture
async def room(hass: HomeAssistant, fleet: MockConfigEntry) -> MockConfigEntry:
    """Room "Room A" with A1 and A2, every thermostat holding the night-long schedule."""
    await hass.services.async_call(
        DOMAIN,
        "create_room",
        {"name": "Room A", "thermostats": ["Thermostat A1", "Thermostat A2"]},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()
    await publish_bridge(hass, FLEET, {d["friendly_name"]: with_schedule(WEEK) for d in FLEET})
    await bridge_info(hass)
    return fleet


def requests(mqtt_mock: Any) -> list[tuple[str, dict[str, Any]]]:
    return [
        (call.args[0], json.loads(call.args[1]))
        for call in mqtt_mock.async_publish.mock_calls
        if "/bridge/request/" in call.args[0]
    ]


def written(name: str, request: dict[str, Any]) -> Response:
    """The bridge writes the days and reads them back."""
    week = {**WEEK, **request.get("days", {})}
    return {
        "status": "ok",
        "data": {
            "device": name,
            "days": list(request.get("days", {})),
            "written": 2,
            "confirmed": True,
            "schedule": week,
        },
    }


async def run(
    hass: HomeAssistant,
    mqtt_mock: Any,
    call: Any,
    answers: dict[str, Callable[[str, dict[str, Any]], Response]] | None = None,
) -> Any:
    """Run a service call, answering each request as the bridge would."""
    task = hass.async_create_task(call)
    handled = 0
    while not task.done():
        sent = requests(mqtt_mock)
        for topic, request in sent[handled:]:
            action = topic.split("/bridge/request/")[1]
            name = request["device"]
            response = (answers or {}).get(name, written)(name, request)
            if response is not None:
                fire(
                    hass,
                    f"{TUYA}/bridge/response/{action}",
                    {**response, "transaction": request["transaction"]},
                )
        handled = len(sent)
        await asyncio.sleep(0)
    return await task


def service(hass: HomeAssistant, action: str, **data: Any) -> Any:
    return hass.services.async_call(DOMAIN, action, data, blocking=True, return_response=True)


# -- the codec of the Companion ------------------------------------------------------------------


def test_normalise_checks_a_day_in_full() -> None:
    assert schedule.normalise({"sunday": NIGHT, "monday": DAY}) == {"monday": DAY, "sunday": NIGHT}
    merged = [
        {"time": "07:30", "temperature": 19},
        {"time": "00:00", "temperature": 7},
        {"time": "06:00", "temperature": 7},
    ]
    assert schedule.normalise_day("friday", merged) == [
        {"time": "00:00", "temperature": 7.0},
        {"time": "07:30", "temperature": 19.0},
    ]
    cases: list[tuple[Any, str]] = [
        ({}, "schedule_no_day"),
        ({"funday": NIGHT}, "schedule_day_unknown"),
        ({"monday": []}, "schedule_day_empty"),
        ({"monday": [{"time": "06:00", "temperature": 19}]}, "schedule_day_start"),
        ({"monday": [{"time": "00:00"}]}, "schedule_transition_invalid"),
        ({"monday": [{"time": "00:00", "temperature": 7, "x": 1}]}, "schedule_transition_invalid"),
        ({"monday": [{"time": "00:10", "temperature": 7}]}, "schedule_time_invalid"),
        ({"monday": [{"time": "24:00", "temperature": 7}]}, "schedule_time_invalid"),
        ({"monday": [{"time": "7h", "temperature": 7}]}, "schedule_time_invalid"),
        ({"monday": [{"time": 0, "temperature": 7}]}, "schedule_time_invalid"),
        ({"monday": [{"time": "00:60", "temperature": 7}]}, "schedule_time_invalid"),
        ({"monday": [*NIGHT, {"time": "00:00", "temperature": 9}]}, "schedule_time_repeated"),
        ({"monday": [{"time": "00:00", "temperature": 31}]}, "schedule_temperature_invalid"),
        ({"monday": [{"time": "00:00", "temperature": 19.2}]}, "schedule_temperature_invalid"),
        ({"monday": [{"time": "00:00", "temperature": True}]}, "schedule_temperature_invalid"),
    ]
    for days, code in cases:
        with pytest.raises(schedule.ScheduleError) as caught:
            schedule.normalise(days)
        assert caught.value.code == code, days


def test_read_and_common() -> None:
    assert schedule.read(None) is None and schedule.read({"monday": "x"}) is None
    assert schedule.read({"monday": NIGHT, "tuesday": []}) == {"monday": NIGHT}
    other = {**WEEK, "saturday": DAY}
    assert schedule.common([WEEK, WEEK]) == (WEEK, [])
    shared, differing = schedule.common([WEEK, other])
    assert differing == ["saturday"] and shared is not None and "saturday" not in shared
    assert schedule.common([WEEK, None]) == (None, [])
    assert schedule.common([{"monday": NIGHT}, {"tuesday": NIGHT}]) == (None, [])
    assert schedule.common([]) == (None, [])


# -- reading -------------------------------------------------------------------------------------


async def test_the_schedule_is_an_attribute_of_thermostat_and_room(
    hass: HomeAssistant, room: MockConfigEntry
) -> None:
    b1 = hass.states.get(B1)
    assert b1 is not None
    assert b1.attributes["schedule"] == WEEK
    assert b1.attributes["schedule_read_at"] == "2026-11-28T10:00:00Z"
    state = hass.states.get(ROOM)
    assert state is not None
    assert (
        state.attributes["schedule"] == WEEK and state.attributes["schedule_differing_days"] == []
    )
    assert "schedule" not in state.attributes["differing"]

    fire(hass, f"{TUYA}/Thermostat A2", with_schedule({**WEEK, "saturday": DAY}))
    await hass.async_block_till_done()
    state = hass.states.get(ROOM)
    assert state is not None
    assert state.attributes["schedule_differing_days"] == ["saturday"]
    assert "saturday" not in state.attributes["schedule"]
    assert "schedule" in state.attributes["differing"]

    fire(hass, f"{TUYA}/Thermostat A2", with_schedule(None))
    await hass.async_block_till_done()
    state = hass.states.get(ROOM)
    assert state is not None and state.attributes["schedule"] is None


async def test_get_schedule_from_the_last_reading(
    hass: HomeAssistant, room: MockConfigEntry
) -> None:
    answer = await service(hass, "get_schedule", room="Room A")
    assert answer["target"] == "Room A" and answer["schedule"] == WEEK
    assert answer["thermostats"]["Thermostat A1"] == {
        "schedule": WEEK,
        "read_at": "2026-11-28T10:00:00Z",
    }
    answer = await service(hass, "get_schedule", thermostat="Thermostat B1")
    assert list(answer["thermostats"]) == ["Thermostat B1"]


async def test_get_schedule_refresh_asks_the_bridge(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    def read(name: str, request: dict[str, Any]) -> Response:
        return {"status": "ok", "data": {"device": name, "schedule": {**WEEK, "monday": DAY}}}

    answer = await run(
        hass, mqtt_mock, service(hass, "get_schedule", thermostat="Thermostat B1", refresh=True),
        {"Thermostat B1": read},
    )  # fmt: skip
    assert answer["thermostats"]["Thermostat B1"]["schedule"]["monday"] == DAY
    ((topic, request),) = requests(mqtt_mock)
    assert topic == f"{TUYA}/bridge/request/schedule/get"
    assert request["device"] == "Thermostat B1"

    def refused(name: str, request: dict[str, Any]) -> Response:
        return {"status": "error", "error": "schedule: down", "data": {"device": name}}

    with pytest.raises(HomeAssistantError, match="schedule: down"):
        await run(
            hass, mqtt_mock, service(hass, "get_schedule", thermostat=B1_NAME, refresh=True),
            {B1_NAME: refused},
        )  # fmt: skip

    await bridge_info(hass, developer="offline")
    with pytest.raises(ServiceValidationError, match="developer channel"):
        await service(hass, "get_schedule", thermostat="Thermostat B1", refresh=True)


async def test_service_targets(hass: HomeAssistant, room: MockConfigEntry) -> None:
    with pytest.raises(ServiceValidationError, match="either a room or a thermostat"):
        await service(hass, "get_schedule")
    with pytest.raises(ServiceValidationError, match="either a room or a thermostat"):
        await service(hass, "get_schedule", room="Room A", thermostat="Thermostat B1")
    await hass.services.async_call(DOMAIN, "create_room", {"name": "Empty"}, blocking=True)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError, match="has no thermostat"):
        await service(hass, "get_schedule", room="Empty")


# -- writing -------------------------------------------------------------------------------------


async def test_set_schedule_to_a_room_one_thermostat_after_the_other(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    answer = await run(
        hass, mqtt_mock,
        service(hass, "set_schedule", room="Room A", days=["saturday", "sunday"], transitions=DAY),
    )  # fmt: skip
    assert answer["target"] == "Room A"
    assert answer["thermostats"]["Thermostat A1"]["confirmed"] is True
    assert answer["thermostats"]["Thermostat A2"]["schedule"]["sunday"] == DAY
    sent = requests(mqtt_mock)
    assert [request["device"] for _, request in sent] == ["Thermostat A1", "Thermostat A2"]
    assert all(topic == f"{TUYA}/bridge/request/schedule/set" for topic, _ in sent)
    assert sent[0][1]["days"] == {"saturday": DAY, "sunday": DAY}
    assert sent[0][1]["transaction"] != sent[1][1]["transaction"]


async def test_set_schedule_with_a_schedule_per_day(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    await run(
        hass, mqtt_mock,
        service(hass, "set_schedule", thermostat="Thermostat B1", schedule={"monday": DAY}),
    )  # fmt: skip
    ((_, request),) = requests(mqtt_mock)
    assert request["days"] == {"monday": DAY}
    with pytest.raises(ServiceValidationError, match="either schedule"):
        await service(
            hass,
            "set_schedule",
            thermostat="Thermostat B1",
            schedule={"monday": DAY},
            days=["monday"],
        )
    with pytest.raises(ServiceValidationError, match="either schedule"):
        await service(hass, "set_schedule", thermostat="Thermostat B1", days=["monday"])


async def test_set_schedule_refusals_send_nothing(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    with pytest.raises(ServiceValidationError, match="must be at 00:00"):
        await service(
            hass, "set_schedule", thermostat="Thermostat B1", days=["monday"],
            transitions=[{"time": "06:00", "temperature": 19}],
        )  # fmt: skip
    with pytest.raises(ServiceValidationError, match="does not open the schedule write"):
        await service(
            hass, "set_schedule", thermostat="Thermostat B2", days=["monday"], transitions=NIGHT
        )
    fire(hass, f"{TUYA}/Thermostat A2/availability", {"state": "offline"})
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError, match="Not responding"):
        await service(hass, "set_schedule", room="Room A", days=["monday"], transitions=NIGHT)
    await bridge_info(hass, requests=[])
    with pytest.raises(ServiceValidationError, match="does not open the schedule write"):
        await service(
            hass, "set_schedule", thermostat="Thermostat B1", days=["monday"], transitions=NIGHT
        )
    fire(hass, f"{TUYA}/bridge/info", {"version": "0.3.0", "contract": 5, "read_only": False})
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError, match="does not open the schedule write"):
        await service(
            hass, "set_schedule", thermostat="Thermostat B1", days=["monday"], transitions=NIGHT
        )
    assert requests(mqtt_mock) == []
    coordinator = room.runtime_data.coordinator
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_schedule_many([], {"monday": NIGHT})
    assert not coordinator.supports_schedule_set("nobody")
    assert not coordinator.supports_schedule_get("nobody")
    with pytest.raises(ServiceValidationError):
        await coordinator.async_get_schedule("nobody")


async def test_set_schedule_not_confirmed_names_each_thermostat(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    def deaf(name: str, request: dict[str, Any]) -> Response:
        return {
            "status": "error",
            "error": "schedule: not confirmed, the schedule read back differs after 30 s",
            "data": {"device": name, "confirmed": False, "schedule": WEEK},
        }

    def liar(name: str, request: dict[str, Any]) -> Response:  # says ok, reads back otherwise
        return {"status": "ok", "data": {"device": name, "confirmed": True, "schedule": WEEK}}

    with pytest.raises(HomeAssistantError) as caught:
        await run(
            hass, mqtt_mock,
            service(hass, "set_schedule", room="Room A", days=["saturday"], transitions=DAY),
            {"Thermostat A1": deaf, "Thermostat A2": liar},
        )  # fmt: skip
    placeholders = caught.value.translation_placeholders or {}
    assert "Thermostat A1 (schedule: not confirmed" in placeholders["failed"]
    assert "Thermostat A2 (the schedule read back differs)" in placeholders["failed"]
    assert placeholders["confirmed"] == "none"
    assert len(requests(mqtt_mock)) == 2


async def test_set_schedule_without_an_answer(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    with (
        patch("custom_components.tuya_pilot_wire.coordinator.SCHEDULE_TIMEOUT", 0.05),
        pytest.raises(HomeAssistantError) as caught,
    ):
        await run(
            hass, mqtt_mock,
            service(hass, "set_schedule", room="Room A", days=["monday"], transitions=NIGHT),
            {"Thermostat A1": lambda name, request: None},
        )  # fmt: skip
    placeholders = caught.value.translation_placeholders or {}
    assert placeholders["failed"] == "Thermostat A1 (no answer)"
    assert placeholders["confirmed"] == "Thermostat A2"


async def test_two_writes_to_one_thermostat_are_spaced(
    hass: HomeAssistant, room: MockConfigEntry, mqtt_mock: Any
) -> None:
    with patch("custom_components.tuya_pilot_wire.coordinator.MIN_SET_INTERVAL", 0.3):
        start = time.monotonic()
        for _ in range(2):
            call = service(
                hass, "set_schedule", thermostat=B1_NAME, days=["monday"], transitions=NIGHT
            )
            await run(hass, mqtt_mock, call)
        assert time.monotonic() - start >= 0.3
