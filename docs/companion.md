# The Companion, read only (milestone M3)

Status: built and tested against synthetic messages that follow the
[MQTT contract](https://github.com/aghulas/tuyapilot2mqtt/blob/main/docs/mqtt-contract.md).
It publishes **nothing**: no `/set` key is open (`const.OPEN_SET_KEYS` is empty) and reading needs
no request to a bridge. Writes arrive with M4, one route at a time.

## What it reads

For each configured prefix (default `zigbee2mqtt`, `tuyapilot2mqtt`):

| Topic | Use |
|---|---|
| `<prefix>/bridge/state` | the bridge is online or not |
| `<prefix>/bridge/devices` | the fleet: only supported pilot-wire thermostats are kept |
| `<prefix>/bridge/info` | versions and channel states, for diagnostics |
| `<prefix>/<friendly_name>` | the thermostat's state object |
| `<prefix>/<friendly_name>/availability` | the thermostat is online or not |

A thermostat is recognised by `tuya.product_id` on the Tuya bridge, and on Zigbee2MQTT by model id
`TS0601` with a manufacturer name ending in the product id ([`device.md`](device.md)). Everything
else under a prefix is ignored.

## Reading rules

- **The state is the last object published.** A property absent from it is unknown: its entity is
  unavailable. Nothing is kept from an earlier message. (Voltage and current, which exist only
  while heating, are unavailable when idle instead of showing the last heating value.)
- **A thermostat is usable** while its bridge says `online` and its own availability is not
  `offline`. A bridge that has not said `online` yet counts as not online.
- **An entity exists once its value has existed**: it is created the first time a bridge
  publishes the property, and again at start-up because the entity registry knows it. No entity
  is created on the assumption that a bridge will publish something.
- **Identity** is the Tuya device id when the bridge gives one, else the IEEE address. When a
  bridge gives both, the pair is remembered: the same thermostat later published by Zigbee2MQTT,
  by IEEE address alone, keeps its entities.
- Contract draft-0 names (`schedule`, `frost_protection`, `frost_protection_temperature`) are read
  as aliases of the current ones.

## Entities

Per thermostat (device named after its bridge name):

| Entity | Source |
|---|---|
| `climate` (only while the thermostat is in no room) | `system_mode`, `running_state`, `local_temperature`; attributes `preset`, `target_temperature` and the setpoints read |
| `sensor` temperature, setpoint, mode | `local_temperature`; setpoint of the current preset; `preset` |
| `sensor` power, energy, voltage, current | `power`, `energy` (kWh, `total_increasing`, usable in the Energy dashboard), `voltage`, `current` |
| `binary_sensor` heating, window, fault | `running_state`, `window_open`, `fault` (names in the `faults` attribute) |

The **setpoint** is the one the thermostat regulates on: `current_heating_setpoint` in `manual`,
`eco_temperature`, `holiday_temperature` or `antifrost_temperature` in those presets, and nothing
in `program` (its target is in no data point) or when off.

The `climate` declares no feature and lists a single HVAC mode, the reported one, so the interface
offers no control; a service call that tries anyway is refused. Home Assistant shows a climate's
target only with the control that sets it, hence the `target_temperature` attribute and the
setpoint sensor.

## Rooms

A room is a name and a list of thermostats, kept in Home Assistant storage; a thermostat belongs
to one room at most. Creating, editing or deleting a room sends nothing to any device.

- **Options flow**: Settings → Devices & services → Tuya Pilot Wire Companion → Configure → add,
  edit or delete a room.
- **Services**: `tuya_pilot_wire.create_room`, `update_room`, `delete_room`, `list_rooms`. A room
  is named by its device id or its name; a thermostat by its device id or its bridge name.

Per room (a device named after the room):

| Value | Rule |
|---|---|
| temperature | mean of the members that report one |
| on / off, mode, setpoint | the members' common value; unknown when they differ |
| "Thermostats disagree" | on when on / off, mode or setpoint differ; the `differing` attribute names which |
| heating, window, fault | on as soon as one member says so; off only when every member says not; else unavailable |
| power, energy | sums, only when **every** member reports the figure; else unavailable |

A partial energy sum would read as a drop, and an energy counter that drops is read as a reset.
For the same reason, changing a room's members shifts the room's energy counter: for the Energy
dashboard, the per-thermostat energy sensors are the stable choice.

A thermostat in a room keeps its sensors and binary sensors; only its own `climate` is replaced
by the room's.

## Diagnostics

Downloadable from the integration page. Thermostats and rooms are numbered instead of named; no
device id, IEEE address, gateway id, account, key or address is included. Measured values, modes
and the property names each bridge publishes are kept.
