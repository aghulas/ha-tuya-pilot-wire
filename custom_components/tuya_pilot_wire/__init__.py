"""Tuya Pilot Wire Companion.

Skeleton: the entry is set up and stores its bridge prefixes, and creates no entity yet. The
device model, rooms and platforms arrive with milestone M3 (docs/roadmap.md).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Companion from a config entry."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True
