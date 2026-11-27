"""Test configuration: synthetic bridges on a mocked broker. No real device, id or site name."""

from __future__ import annotations

import json
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.tuya_pilot_wire.const import CONF_MQTT_PREFIXES, DOMAIN

TUYA = "tuyapilot2mqtt"
Z2M = "zigbee2mqtt"

STATE: dict[str, Any] = {
    "local_temperature": 19.5,
    "current_heating_setpoint": 20.0,
    "system_mode": "heat",
    "preset": "manual",
    "running_state": "heat",
    "window_open": False,
    "window_detection": "OFF",
    "child_lock": "LOCK",
    "eco_temperature": 16.0,
    "antifrost_temperature": 7.0,
    "holiday_temperature": 5.0,
    "power": 1000.0,
    "voltage": 230.0,
    "current": 4.35,
    "energy": 100.5,
    "fault": [],
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from custom_components."""


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The mocked MQTT client leaves its periodic timer behind; it is not ours to cancel."""
    return True


def descriptor(name: str, dev_id: str, ieee: str | None = None) -> dict[str, Any]:
    """A `bridge/devices` entry as `tuyapilot2mqtt` publishes it (contract §2)."""
    entry: dict[str, Any] = {
        "friendly_name": name,
        "type": "EndDevice",
        "supported": True,
        "definition": {"vendor": "Tuya", "model": "TS0601_fu1bfwza", "description": "Thermostat"},
        "tuya": {
            "dev_id": dev_id,
            "product_id": "fu1bfwza",
            "category": "wk",
            "gateway": "gateway-0001",
        },
    }
    if ieee:
        entry["ieee_address"] = ieee
    return entry


def z2m_descriptor(name: str, ieee: str) -> dict[str, Any]:
    """A `bridge/devices` entry as Zigbee2MQTT publishes it for the same product."""
    return {
        "friendly_name": name,
        "ieee_address": ieee,
        "type": "Router",
        "model_id": "TS0601",
        "manufacturer": "_TZE204_fu1bfwza",
        "supported": True,
        "definition": {"vendor": "Tuya", "model": "TS0601_fu1bfwza"},
    }


def fire(hass: HomeAssistant, topic: str, payload: Any) -> None:
    """Publish on the mocked broker; dicts and lists go as JSON."""
    async_fire_mqtt_message(
        hass, topic, payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
    )


async def publish_bridge(
    hass: HomeAssistant,
    devices: list[dict[str, Any]],
    states: dict[str, dict[str, Any]] | None = None,
    prefix: str = TUYA,
) -> None:
    """Publish a bridge that is online, its device list, and each thermostat's state."""
    fire(hass, f"{prefix}/bridge/state", {"state": "online"})
    fire(hass, f"{prefix}/bridge/devices", devices)
    for entry in devices:
        name = entry["friendly_name"]
        fire(hass, f"{prefix}/{name}/availability", {"state": "online"})
        fire(hass, f"{prefix}/{name}", (states or {}).get(name, STATE))
    await hass.async_block_till_done()


@pytest.fixture
async def entry(hass: HomeAssistant, mqtt_mock: Any) -> MockConfigEntry:
    """The Companion set up on a mocked broker, reading both default prefixes."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, title="Tuya Pilot Wire", data={CONF_MQTT_PREFIXES: [Z2M, TUYA]}
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
async def fleet(hass: HomeAssistant, entry: MockConfigEntry) -> MockConfigEntry:
    """Four thermostats behind the Tuya bridge: A1, A2, B1, B2."""
    await publish_bridge(
        hass,
        [
            descriptor("Thermostat A1", "dev-a1"),
            descriptor("Thermostat A2", "dev-a2"),
            descriptor("Thermostat B1", "dev-b1"),
            descriptor("Thermostat B2", "dev-b2"),
        ],
    )
    return entry
