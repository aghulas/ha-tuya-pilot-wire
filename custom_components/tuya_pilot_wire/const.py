"""Constants of the Tuya Pilot Wire Companion."""

from homeassistant.const import Platform

DOMAIN = "tuya_pilot_wire"

CONF_MQTT_PREFIXES = "mqtt_prefixes"
DEFAULT_MQTT_PREFIXES = ("zigbee2mqtt", "tuyapilot2mqtt")

PLATFORMS = (Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.SENSOR)

# Products recognised as pilot-wire thermostats (docs/device.md). The Tuya product id is also the
# suffix of the Zigbee manufacturer name (`_TZE204_fu1bfwza`).
SUPPORTED_PRODUCT_IDS = frozenset({"fu1bfwza"})
ZIGBEE_MODEL_ID = "TS0601"

# `/set` keys the Companion is allowed to publish. Empty: no write is open in the Companion yet
# (milestone M4 opens them one at a time, each after its supervised trial).
OPEN_SET_KEYS: frozenset[str] = frozenset()

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
