"""Weekly schedule: the shape the bridges publish (contract §5), checked before anything is sent.

A **schedule** is ``{day: [transition, …]}`` with days ``monday`` to ``sunday``; a **day** is its
setpoint changes in time order, ``{"time": "HH:MM", "temperature": °C}``. A day is described in
full: first change at 00:00, times on a 15-minute step and distinct, temperatures on a 0.5 °C step
between 5 and 30 °C (the bridge's library refuses anything else, nothing sent).

Plain functions, no Home Assistant object. Nothing here knows Tuya: the data points and their
encoding are the bridge's.
"""

from __future__ import annotations

from typing import Any

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
STEP_MINUTES = 15
MIN_TEMPERATURE = 5.0
MAX_TEMPERATURE = 30.0
TEMPERATURE_STEP = 0.5


class ScheduleError(ValueError):
    """A schedule that cannot be sent. ``code`` is a translation key."""

    def __init__(self, code: str, **placeholders: str) -> None:
        super().__init__(code)
        self.code = code
        self.placeholders = placeholders


def _minutes(day: str, time: Any) -> int:
    if not isinstance(time, str):
        raise ScheduleError("schedule_time_invalid", day=day, time=str(time))
    hours, _, minutes = time.partition(":")
    if not (hours.isdigit() and minutes.isdigit() and len(minutes) == 2):
        raise ScheduleError("schedule_time_invalid", day=day, time=time)
    total = int(hours) * 60 + int(minutes)
    if int(minutes) >= 60 or total >= 24 * 60 or total % STEP_MINUTES:
        raise ScheduleError("schedule_time_invalid", day=day, time=time)
    return total


def _temperature(day: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ScheduleError("schedule_temperature_invalid", day=day, temperature=str(value))
    doubled = value / TEMPERATURE_STEP
    if not MIN_TEMPERATURE <= value <= MAX_TEMPERATURE or abs(doubled - round(doubled)) > 1e-6:
        raise ScheduleError("schedule_temperature_invalid", day=day, temperature=f"{value:g}")
    return round(doubled) * TEMPERATURE_STEP


def normalise_day(day: str, transitions: Any) -> list[dict[str, Any]]:
    """A day's changes, checked and in the contract's shape. Raises ``ScheduleError``.

    Sorted by time; consecutive changes to the same temperature are merged, as the bridge reads
    them back.
    """
    if day not in DAYS:
        raise ScheduleError("schedule_day_unknown", day=str(day))
    if not isinstance(transitions, list) or not transitions:
        raise ScheduleError("schedule_day_empty", day=day)
    pairs: list[tuple[int, float]] = []
    for transition in transitions:
        if not isinstance(transition, dict) or set(transition) != {"time", "temperature"}:
            raise ScheduleError("schedule_transition_invalid", day=day)
        pairs.append(
            (_minutes(day, transition["time"]), _temperature(day, transition["temperature"]))
        )
    pairs.sort()
    if pairs[0][0] != 0:
        raise ScheduleError("schedule_day_start", day=day)
    out: list[dict[str, Any]] = []
    previous_time: int | None = None
    for minutes, temperature in pairs:
        if minutes == previous_time:
            raise ScheduleError("schedule_time_repeated", day=day, time=_hhmm(minutes))
        previous_time = minutes
        if out and out[-1]["temperature"] == temperature:
            continue
        out.append({"time": _hhmm(minutes), "temperature": temperature})
    return out


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def normalise(days: Any) -> dict[str, list[dict[str, Any]]]:
    """Days to write, checked, in week order. Raises ``ScheduleError``."""
    if not isinstance(days, dict) or not days:
        raise ScheduleError("schedule_no_day")
    checked = {day: normalise_day(day, transitions) for day, transitions in days.items()}
    return {day: checked[day] for day in DAYS if day in checked}


def read(value: Any) -> dict[str, list[dict[str, Any]]] | None:
    """A schedule published by a bridge, as days in week order; None when it is not one.

    Days that do not read as a schedule are left out; a schedule with no readable day is None.
    """
    if not isinstance(value, dict):
        return None
    week: dict[str, list[dict[str, Any]]] = {}
    for day in DAYS:
        try:
            week[day] = normalise_day(day, value.get(day))
        except ScheduleError:
            continue
    return week or None


def common(
    schedules: list[dict[str, list[dict[str, Any]]] | None],
) -> tuple[dict[str, list[dict[str, Any]]] | None, list[str]]:
    """``(shared schedule, days that differ)`` over the members of a room.

    A day is in the shared schedule when every member reports it and all report the same; a day
    that two members report differently is named as differing. A member with no schedule read
    leaves the room's schedule unknown (None) without a disagreement, as for any room value.
    """
    known = [week for week in schedules if week is not None]
    differing = [day for day in DAYS if len({_key(week[day]) for week in known if day in week}) > 1]
    if not schedules or len(known) != len(schedules):
        return None, differing
    shared = {
        day: known[0][day]
        for day in DAYS
        if day not in differing and all(day in week for week in known)
    }
    return shared or None, differing


def _key(day: list[dict[str, Any]]) -> tuple[tuple[str, float], ...]:
    return tuple((transition["time"], transition["temperature"]) for transition in day)
