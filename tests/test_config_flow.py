"""Config flow of the Companion."""

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.tuya_pilot_wire.config_flow import parse_prefixes
from custom_components.tuya_pilot_wire.const import CONF_MQTT_PREFIXES, DOMAIN


@pytest.fixture(autouse=True)
def broker(mqtt_mock: Any) -> None:
    """The entry is set up at the end of the flow: it needs the (mocked) broker."""


def test_parse_prefixes() -> None:
    assert parse_prefixes(" zigbee2mqtt, tuyapilot2mqtt ,zigbee2mqtt,") == [
        "zigbee2mqtt",
        "tuyapilot2mqtt",
    ]


@pytest.mark.parametrize("text", ["", " , ", "a/b", "zigbee2mqtt, #", "with space"])
def test_parse_prefixes_refuses(text: str) -> None:
    with pytest.raises(ValueError):
        parse_prefixes(text)


async def test_user_flow_creates_the_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MQTT_PREFIXES: "zigbee2mqtt, tuyapilot2mqtt"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_MQTT_PREFIXES: ["zigbee2mqtt", "tuyapilot2mqtt"]}


async def test_user_flow_shows_an_error_on_a_bad_prefix(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MQTT_PREFIXES: "zigbee2mqtt/#"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_MQTT_PREFIXES: "invalid_prefixes"}
