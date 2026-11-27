"""Config and options flows of the Tuya Pilot Wire Companion.

Config flow: the MQTT prefixes of the bridges to read. Options flow: those prefixes again, and
the rooms (add, edit, delete), which live in Home Assistant storage and touch no device.
"""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    ATTR_NAME,
    ATTR_ROOM,
    ATTR_THERMOSTATS,
    CONF_MQTT_PREFIXES,
    DEFAULT_MQTT_PREFIXES,
    DOMAIN,
)
from .rooms import RoomError

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


def _prefix_schema(text: str) -> vol.Schema:
    return vol.Schema({vol.Required(CONF_MQTT_PREFIXES, default=text): str})


class TuyaPilotWireConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry, holding the bridge prefixes."""

    VERSION = 1
    # 1.2 (v0.3.0): the `trial_thermostat` option is gone (`async_migrate_entry`).
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CompanionOptionsFlow:
        """The options flow."""
        return CompanionOptionsFlow()

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
        return self.async_show_form(step_id="user", data_schema=_prefix_schema(text), errors=errors)


class CompanionOptionsFlow(OptionsFlow):
    """Bridge prefixes and rooms."""

    _room_id: str | None = None

    @property
    def _data(self) -> Any:
        return self.config_entry.runtime_data

    def _done(self) -> ConfigFlowResult:
        """Close the flow after a room change: options untouched, entry reloaded."""
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)
        return self.async_create_entry(data=dict(self.config_entry.options))

    def _room_selector(self) -> SelectSelector:
        return SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=room.id, label=room.name)
                    for room in self._data.store.rooms.values()
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )

    def _thermostat_selector(self, room_id: str | None) -> SelectSelector:
        """The thermostats that can be in this room: its own, and those outside any room."""
        store = self._data.store
        thermostats = self._data.coordinator.thermostats
        options: list[SelectOptionDict] = []
        own = store.rooms[room_id].members if room_id else []
        for key in [*own, *(k for k in thermostats if k not in own)]:
            owner = store.room_of(key)
            if owner is not None and owner.id != room_id:
                continue
            label = thermostats[key].friendly_name if key in thermostats else key
            options.append(SelectOptionDict(value=key, label=label))
        return SelectSelector(
            SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST)
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Menu."""
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        options = ["bridges", "add_room"]
        if self._data.store.rooms:
            options += ["edit_room", "delete_room"]
        return self.async_show_menu(step_id="init", menu_options=options)

    async def async_step_bridges(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the bridge prefixes."""
        errors: dict[str, str] = {}
        text = ", ".join(self._data.coordinator.prefixes)
        if user_input is not None:
            text = user_input[CONF_MQTT_PREFIXES]
            try:
                prefixes = parse_prefixes(text)
            except ValueError:
                errors[CONF_MQTT_PREFIXES] = "invalid_prefixes"
            else:
                # The update listener reloads the entry when the options change.
                return self.async_create_entry(
                    data={**self.config_entry.options, CONF_MQTT_PREFIXES: prefixes}
                )
        return self.async_show_form(
            step_id="bridges", data_schema=_prefix_schema(text), errors=errors
        )

    async def async_step_add_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a room."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._data.store.create(user_input[ATTR_NAME], user_input.get(ATTR_THERMOSTATS, []))
            except RoomError as err:
                errors["base"] = err.code
            else:
                return self._done()
        schema = vol.Schema(
            {
                vol.Required(ATTR_NAME): str,
                vol.Optional(ATTR_THERMOSTATS, default=[]): self._thermostat_selector(None),
            }
        )
        return self.async_show_form(
            step_id="add_room",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_edit_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the room to edit."""
        if user_input is not None:
            self._room_id = user_input[ATTR_ROOM]
            return await self.async_step_room()
        return self.async_show_form(
            step_id="edit_room",
            data_schema=vol.Schema({vol.Required(ATTR_ROOM): self._room_selector()}),
        )

    async def async_step_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rename the chosen room and choose its thermostats."""
        assert self._room_id is not None
        room = self._data.store.rooms[self._room_id]
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._data.store.update(
                    room.id, user_input[ATTR_NAME], user_input.get(ATTR_THERMOSTATS, [])
                )
            except RoomError as err:
                errors["base"] = err.code
            else:
                return self._done()
        schema = vol.Schema(
            {
                vol.Required(ATTR_NAME): str,
                vol.Optional(ATTR_THERMOSTATS, default=[]): self._thermostat_selector(room.id),
            }
        )
        suggested = user_input or {ATTR_NAME: room.name, ATTR_THERMOSTATS: list(room.members)}
        return self.async_show_form(
            step_id="room",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders={"room": room.name},
        )

    async def async_step_delete_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delete a room."""
        if user_input is not None:
            self._data.store.delete(user_input[ATTR_ROOM])
            return self._done()
        return self.async_show_form(
            step_id="delete_room",
            data_schema=vol.Schema({vol.Required(ATTR_ROOM): self._room_selector()}),
        )
