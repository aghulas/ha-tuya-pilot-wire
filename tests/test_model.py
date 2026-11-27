"""Device model: descriptors and state objects."""

import pytest

from custom_components.tuya_pilot_wire.model import (
    Thermostat,
    descriptor_identity,
    is_thermostat,
    normalise_state,
    thermostat_from_descriptor,
)

from .conftest import STATE, descriptor, z2m_descriptor


def make(**state) -> Thermostat:
    return Thermostat("k", "p", "n", state=normalise_state(state))


def test_recognises_the_product_on_both_bridges() -> None:
    assert is_thermostat(descriptor("A", "dev-1"))
    assert is_thermostat(z2m_descriptor("A", "0x01"))
    assert is_thermostat({"model_id": "TS0601", "manufacturer": "_TZE284_fu1bfwza"})


@pytest.mark.parametrize(
    "entry",
    [
        {"friendly_name": "Coordinator", "type": "Coordinator"},
        {"model_id": "TS0601", "manufacturer": "_TZE204_other000"},
        {"model_id": "TS0601", "manufacturer": None},
        {"model_id": "eTRV0100", "manufacturer": "_TZE204_fu1bfwza"},
        {"tuya": "not an object"},
        {"tuya": {"product_id": "other000"}},
    ],
)
def test_ignores_everything_else(entry: dict) -> None:
    assert not is_thermostat(entry)


def test_identity_and_descriptor() -> None:
    entry = descriptor("A", "dev-1", "0xAB")
    assert descriptor_identity(entry) == ("dev-1", "0xab")
    assert descriptor_identity({}) == (None, None)
    thermostat = thermostat_from_descriptor(entry, "p", "dev-1")
    assert thermostat is not None
    assert (thermostat.vendor, thermostat.model, thermostat.ieee_address) == (
        "Tuya",
        "TS0601_fu1bfwza",
        "0xab",
    )
    assert thermostat_from_descriptor({"friendly_name": ""}, "p", "k") is None
    bare = thermostat_from_descriptor({"friendly_name": "A", "model_id": "TS0601"}, "p", "k")
    assert bare is not None and bare.model == "TS0601" and bare.vendor is None


def test_reads_a_full_state() -> None:
    t = make(**STATE)
    assert t.local_temperature == 19.5
    assert t.system_mode == "heat"
    assert t.preset == "manual"
    assert t.target_temperature == 20.0
    assert t.heating is True
    assert t.window_open is False
    assert t.faults == [] and t.fault is False
    assert t.number("energy") == 100.5
    assert t.get("child_lock") == "LOCK"


def test_an_absent_property_is_unknown() -> None:
    t = make()
    assert t.local_temperature is None
    assert t.system_mode is None
    assert t.preset is None
    assert t.target_temperature is None
    assert t.heating is None
    assert t.window_open is None
    assert t.faults is None and t.fault is None


def test_refuses_values_of_the_wrong_type() -> None:
    t = make(
        local_temperature="19.5",
        power=True,
        system_mode="auto",
        preset=3,
        running_state="cool",
        window_open="ajar",
        fault=4,
    )
    assert t.local_temperature is None
    assert t.number("power") is None
    assert t.system_mode is None
    assert t.preset is None
    assert t.heating is None
    assert t.window_open is None
    assert t.fault is None
    assert make(preset="comfort").preset is None


@pytest.mark.parametrize(
    ("preset", "target"),
    [("manual", 20.0), ("eco", 16.0), ("antifrost", 7.0), ("holiday", 5.0), ("program", None)],
)
def test_target_follows_the_preset(preset: str, target: float | None) -> None:
    assert make(**{**STATE, "preset": preset}).target_temperature == target


def test_no_target_when_off() -> None:
    assert make(**{**STATE, "system_mode": "off"}).target_temperature is None


def test_draft_0_names_are_aliases() -> None:
    t = make(
        system_mode="heat",
        preset="frost_protection",
        frost_protection_temperature=7.5,
    )
    assert t.preset == "antifrost"
    assert t.target_temperature == 7.5
    assert make(preset="schedule").preset == "program"
    # The current name wins when a bridge publishes both.
    both = normalise_state({"frost_protection_temperature": 1.0, "antifrost_temperature": 2.0})
    assert both == {"antifrost_temperature": 2.0}


def test_window_and_fault_variants() -> None:
    assert make(window_open="OPEN").window_open is True
    assert make(window_open="close").window_open is False
    assert make(running_state="idle").heating is False
    faulty = make(fault=["e1", "e3"])
    assert faulty.fault is True and faulty.faults == ["e1", "e3"]
