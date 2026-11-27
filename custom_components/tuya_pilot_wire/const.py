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

# `/set` keys the Companion is allowed to publish to any thermostat. Empty: no write is proven
# through the Companion yet (milestone M4 opens them one at a time, each after its trial).
OPEN_SET_KEYS: frozenset[str] = frozenset()

# `/set` keys under supervised trial: publishable to **one** thermostat only, the one the owner
# designates in the options (`CONF_TRIAL_THERMOSTAT`), and only while its bridge says it is not
# read only. A key moves to `OPEN_SET_KEYS` in the change that records its trial.
TRIAL_SET_KEYS: frozenset[str] = frozenset({"current_heating_setpoint"})
CONF_TRIAL_THERMOSTAT = "trial_thermostat"

# Bounds and step of each writable key, checked before anything is published (docs/scope.md).
SET_BOUNDS: dict[str, tuple[float, float, float]] = {"current_heating_setpoint": (5.0, 40.0, 0.5)}

# How long the bridge has to answer a command (it writes, then reads the device back).
SET_TIMEOUT = 45.0

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

ATTR_NAME = "name"
ATTR_ROOM = "room"
ATTR_THERMOSTATS = "thermostats"
