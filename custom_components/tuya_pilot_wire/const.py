"""Constants of the Tuya Pilot Wire Companion."""

from homeassistant.const import Platform

DOMAIN = "tuya_pilot_wire"

CONF_MQTT_PREFIXES = "mqtt_prefixes"
DEFAULT_MQTT_PREFIXES = ("zigbee2mqtt", "tuyapilot2mqtt")

PLATFORMS = (Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.NUMBER, Platform.SENSOR)

# Products recognised as pilot-wire thermostats (docs/device.md). The Tuya product id is also the
# suffix of the Zigbee manufacturer name (`_TZE204_fu1bfwza`).
SUPPORTED_PRODUCT_IDS = frozenset({"fu1bfwza"})
ZIGBEE_MODEL_ID = "TS0601"

# `/set` keys the Companion knows how to build and check. None is open by the Companion itself:
# a key is published to a thermostat only while that thermostat's bridge announces it open for
# it (`bridge/info`: `read_only: false`, the key in `writes.keys`, the thermostat in
# `writes.devices`). The bridge holds the owner's designation and the supervised trials
# (docs/companion.md, "Writes").
SET_KEYS: frozenset[str] = frozenset({"current_heating_setpoint", "preset"})

# Presets the Companion may write: the two the bridge accepts. `eco`, `holiday` and `antifrost`
# are read, never written.
SET_PRESETS: tuple[str, ...] = ("program", "manual")

# Bounds and step of each numeric key, checked before anything is published. The device takes
# 5 to 40 °C by 0.5; the bridge adds a 30 °C ceiling, kept here so that nothing is offered that
# the bridge would refuse.
SET_BOUNDS: dict[str, tuple[float, float, float]] = {"current_heating_setpoint": (5.0, 30.0, 0.5)}

# Option of versions 0.2.x (a single thermostat designated for write trials), dropped by the
# entry migration to 1.2: the bridge now says which thermostats a write is open for.
LEGACY_CONF_TRIAL_THERMOSTAT = "trial_thermostat"

# Shortest gap between two commands to the same thermostat (seconds). The bridge allows one write
# per thermostat every 10 s (and 30 an hour) and refuses the next with nothing sent: a preset then
# a setpoint to the same thermostat waits here instead of being refused there.
MIN_SET_INTERVAL = 10.0

# How long the bridge has to answer a command (it writes, then reads the device back).
SET_TIMEOUT = 45.0

# Weekly schedule (contract §5): the request the Companion can build, and the time the bridge has
# to answer one (it reads the developer API, writes, then reads back for up to 30 s). Like
# `SET_KEYS`, nothing is opened by the Companion: `schedule/set` goes to a thermostat only while
# its bridge lists it in `writes.requests` and the thermostat in `writes.devices`.
SCHEDULE_SET = "schedule/set"
SCHEDULE_GET = "schedule/get"
SCHEDULE_TIMEOUT = 60.0

# `hass.data` key of the coordinator an unloaded entry leaves for the entry set up next.
DATA_HANDOVER = f"{DOMAIN}_handover"

STORAGE_KEY = f"{DOMAIN}.rooms"
STORAGE_VERSION = 1

MANUFACTURER = "Tuya"
ROOM_MODEL = "Room"

SERVICE_CREATE_ROOM = "create_room"
SERVICE_UPDATE_ROOM = "update_room"
SERVICE_DELETE_ROOM = "delete_room"
SERVICE_LIST_ROOMS = "list_rooms"
SERVICE_GET_SCHEDULE = "get_schedule"
SERVICE_SET_SCHEDULE = "set_schedule"

ATTR_NAME = "name"
ATTR_ROOM = "room"
ATTR_THERMOSTATS = "thermostats"
ATTR_THERMOSTAT = "thermostat"
ATTR_SCHEDULE = "schedule"
ATTR_DAYS = "days"
ATTR_TRANSITIONS = "transitions"
ATTR_REFRESH = "refresh"
