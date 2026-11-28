"""Switches: child lock and open-window detection, per thermostat and per room.

Each exists once a bridge opens its `/set` key (`writes.keys`) for the thermostat, or, for a
room, for every member (`CompanionCoordinator.supports_set`); it is unavailable while the key is
closed, while the value is not reported, and, for a room, while the members disagree. A switch
sends one command per thermostat (`async_set_many`); its state does not move until the bridge
publishes what the devices confirmed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CompanionConfigEntry
from .const import SET_CHOICES
from .entity import (
    CompanionDescription,
    RoomSettingEntity,
    ThermostatSettingEntity,
    async_setup_settings,
)


@dataclass(frozen=True, kw_only=True)
class CompanionSwitchDescription(CompanionDescription, SwitchEntityDescription):
    """A switch kind; its key is the `/set` key, its values are `SET_CHOICES` (on, off)."""


SWITCHES: tuple[CompanionSwitchDescription, ...] = (
    CompanionSwitchDescription(
        key="child_lock",
        translation_key="child_lock",
        entity_category=EntityCategory.CONFIG,
        thermostat_fn=lambda t: t.child_lock,
        room_fn=lambda r: r.child_lock,
    ),
    CompanionSwitchDescription(
        key="window_detection",
        translation_key="window_detection",
        entity_category=EntityCategory.CONFIG,
        thermostat_fn=lambda t: t.window_detection,
        room_fn=lambda r: r.window_detection,
    ),
)


class _CompanionSwitch(SwitchEntity):
    """On and off as the key's two values."""

    entity_description: CompanionSwitchDescription
    # From the thermostat or room setting entity.
    reported: Any
    async_write: Callable[[Any], Awaitable[None]]

    @property
    def is_on(self) -> bool | None:
        return self.reported

    async def async_turn_on(self, **kwargs: Any) -> None:
        """WRITE. The key's "on" value (`LOCK`, `ON`)."""
        await self.async_write(SET_CHOICES[self.entity_description.key][0])

    async def async_turn_off(self, **kwargs: Any) -> None:
        """WRITE. The key's "off" value (`UNLOCK`, `OFF`)."""
        await self.async_write(SET_CHOICES[self.entity_description.key][1])


class ThermostatSwitch(ThermostatSettingEntity, _CompanionSwitch):
    """A switch of one thermostat."""


class RoomSwitch(RoomSettingEntity, _CompanionSwitch):
    """A switch of a room."""


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CompanionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switches as the bridges open them."""
    async_setup_settings(
        hass, entry, async_add_entities, "switch", SWITCHES, ThermostatSwitch, RoomSwitch
    )
