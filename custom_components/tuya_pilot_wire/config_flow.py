"""Config flow of the Tuya Pilot Wire Companion: the MQTT prefixes of the bridges to read."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import CONF_MQTT_PREFIXES, DEFAULT_MQTT_PREFIXES, DOMAIN

# One MQTT topic level per prefix: no separator, no wildcard.
_PREFIX = re.compile(r"^[A-Za-z0-9_\-]+$")


def parse_prefixes(text: str) -> list[str]:
    """A comma-separated string to a list of distinct prefixes. Raises ``ValueError``."""
    prefixes: list[str] = []
    for item in text.split(","):
        prefix = item.strip()
        if not prefix:
            continue
        if not _PREFIX.match(prefix):
            raise ValueError(prefix)
        if prefix not in prefixes:
            prefixes.append(prefix)
    if not prefixes:
        raise ValueError("empty")
    return prefixes


class TuyaPilotWireConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry, holding the bridge prefixes."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the bridge prefixes."""
        errors: dict[str, str] = {}
        text = ", ".join(DEFAULT_MQTT_PREFIXES)
        if user_input is not None:
            text = user_input[CONF_MQTT_PREFIXES]
            try:
                prefixes = parse_prefixes(text)
            except ValueError:
                errors[CONF_MQTT_PREFIXES] = "invalid_prefixes"
            else:
                return self.async_create_entry(
                    title="Tuya Pilot Wire", data={CONF_MQTT_PREFIXES: prefixes}
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_MQTT_PREFIXES, default=text): str}),
            errors=errors,
        )
