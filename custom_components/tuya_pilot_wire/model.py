"""Device model of the Companion: one thermostat, whichever bridge publishes it.

Plain data, no Home Assistant object. A thermostat holds the **last state object** its bridge
published and nothing else: a property absent from that object is unknown here (``None``), never
a default and never a previous value. That is the read side of "zero optimistic state".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import schedule
from .const import SUPPORTED_PRODUCT_IDS, ZIGBEE_MODEL_ID

PRESET_PROGRAM = "program"
PRESET_MANUAL = "manual"
PRESET_ECO = "eco"
PRESET_HOLIDAY = "holiday"
PRESET_ANTIFROST = "antifrost"
PRESETS = (PRESET_PROGRAM, PRESET_MANUAL, PRESET_ECO, PRESET_HOLIDAY, PRESET_ANTIFROST)

# Names of contract draft 0, read as aliases (docs/device.md, "Property names").
_PRESET_ALIASES = {"schedule": PRESET_PROGRAM, "frost_protection": PRESET_ANTIFROST}
_PROPERTY_ALIASES = {"frost_protection_temperature": "antifrost_temperature"}

# The property holding the target setpoint of each preset. `program` has none: its target is in no
# data point (docs/scope.md, "Traps").
_PRESET_SETPOINT = {
    PRESET_MANUAL: "current_heating_setpoint",
    PRESET_ECO: "eco_temperature",
    PRESET_HOLIDAY: "holiday_temperature",
    PRESET_ANTIFROST: "antifrost_temperature",
}


def _number(value: Any) -> float | None:
    """A JSON number as a float; anything else (bool, string, null) is unknown."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _on_off(value: Any, on: str, off: str) -> bool | None:
    """A bool, or one of two strings, as a bool; anything else is unknown."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().upper()
        if text == on:
            return True
        if text == off:
            return False
    return None


@dataclass
class Thermostat:
    """One pilot-wire thermostat as its bridge describes it."""

    key: str  # stable identity: Tuya device id when the bridge gives one, else IEEE address
    prefix: str  # bridge that publishes it
    friendly_name: str
    vendor: str | None = None
    model: str | None = None
    ieee_address: str | None = None
    online: bool | None = None  # `<name>/availability`; None until the bridge says
    state: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str) -> Any:
        """Raw value of a property of the last state object, or None."""
        return self.state.get(name)

    def number(self, name: str) -> float | None:
        return _number(self.state.get(name))

    @property
    def local_temperature(self) -> float | None:
        return self.number("local_temperature")

    @property
    def system_mode(self) -> str | None:
        value = self.state.get("system_mode")
        return value if value in ("heat", "off") else None

    @property
    def preset(self) -> str | None:
        value = self.state.get("preset")
        if not isinstance(value, str):
            return None
        value = _PRESET_ALIASES.get(value, value)
        return value if value in PRESETS else None

    @property
    def target_temperature(self) -> float | None:
        """Setpoint the thermostat regulates on, or None when no property holds it."""
        if self.system_mode != "heat":
            return None
        name = _PRESET_SETPOINT.get(self.preset or "")
        return self.number(name) if name else None

    @property
    def schedule(self) -> dict[str, list[dict[str, Any]]] | None:
        """The weekly schedule last read by the bridge (`tuya.schedule`), or None."""
        extension = self.state.get("tuya")
        return schedule.read(extension.get("schedule")) if isinstance(extension, dict) else None

    @property
    def schedule_read_at(self) -> str | None:
        """When the bridge read the schedule (`tuya.read.schedule.at`), or None."""
        extension = self.state.get("tuya")
        read = extension.get("read") if isinstance(extension, dict) else None
        entry = read.get("schedule") if isinstance(read, dict) else None
        at = entry.get("at") if isinstance(entry, dict) else None
        return at if isinstance(at, str) else None

    @property
    def heating(self) -> bool | None:
        value = self.state.get("running_state")
        if value == "heat":
            return True
        if value == "idle":
            return False
        return None

    @property
    def window_open(self) -> bool | None:
        return _on_off(self.state.get("window_open"), "OPEN", "CLOSE")

    @property
    def child_lock(self) -> bool | None:
        return _on_off(self.state.get("child_lock"), "LOCK", "UNLOCK")

    @property
    def window_detection(self) -> bool | None:
        return _on_off(self.state.get("window_detection"), "ON", "OFF")

    @property
    def local_temperature_calibration(self) -> float | None:
        return self.number("local_temperature_calibration")

    @property
    def holiday_temperature(self) -> float | None:
        return self.number("holiday_temperature")

    @property
    def faults(self) -> list[str] | None:
        """Names of the active faults; empty when none; None when the bridge did not read them."""
        value = self.state.get("fault")
        if isinstance(value, list):
            return [str(item) for item in value]
        return None

    @property
    def fault(self) -> bool | None:
        faults = self.faults
        return None if faults is None else bool(faults)


def normalise_state(payload: dict[str, Any]) -> dict[str, Any]:
    """A bridge state object with draft-0 property names mapped to the current ones."""
    state = dict(payload)
    for old, new in _PROPERTY_ALIASES.items():
        if old in state:
            state.setdefault(new, state.pop(old))
    return state


def _tuya_extension(entry: dict[str, Any]) -> dict[str, Any]:
    ext = entry.get("tuya")
    return ext if isinstance(ext, dict) else {}


def is_thermostat(entry: dict[str, Any]) -> bool:
    """True when a `bridge/devices` entry describes a supported pilot-wire thermostat."""
    if _tuya_extension(entry).get("product_id") in SUPPORTED_PRODUCT_IDS:
        return True
    manufacturer = entry.get("manufacturer")
    if entry.get("model_id") == ZIGBEE_MODEL_ID and isinstance(manufacturer, str):
        return manufacturer.rpartition("_")[2] in SUPPORTED_PRODUCT_IDS
    return False


def descriptor_identity(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    """``(tuya device id, IEEE address)`` of a `bridge/devices` entry, each None when absent."""
    dev_id = _tuya_extension(entry).get("dev_id")
    ieee = entry.get("ieee_address")
    return (
        str(dev_id) if dev_id else None,
        str(ieee).lower() if ieee else None,
    )


def thermostat_from_descriptor(entry: dict[str, Any], prefix: str, key: str) -> Thermostat | None:
    """Build a thermostat from a `bridge/devices` entry, or None when it has no topic name."""
    name = entry.get("friendly_name")
    if not isinstance(name, str) or not name:
        return None
    definition = entry.get("definition")
    definition = definition if isinstance(definition, dict) else {}
    return Thermostat(
        key=key,
        prefix=prefix,
        friendly_name=name,
        vendor=definition.get("vendor"),
        model=definition.get("model") or entry.get("model_id"),
        ieee_address=descriptor_identity(entry)[1],
    )
