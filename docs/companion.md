# The Companion (milestones M3 and M4)

Status: the read side is built, tested against synthetic messages that follow the
[MQTT contract](https://github.com/aghulas/tuyapilot2mqtt/blob/main/docs/mqtt-contract.md), and
runs on the reference install. Since v0.3.0 two writes are built, the preset (`program` /
`manual`) and the manual setpoint, on room and thermostat climates. **The Companion opens none by
itself**: each is offered for a thermostat only while its bridge announces it open for that
thermostat (see "Writes" below). Since v0.4.0 the **weekly schedule** is read per thermostat and
per room, and written by the service `set_schedule`, open only where the bridge opens it (see
"Weekly schedule" below).

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
- **A reload keeps the fleet.** When the entry is reloaded (a room change does it), Home
  Assistant's MQTT client keeps its broker subscription, so the retained messages are not sent
  again; the new coordinator therefore starts from the fleet of the one it replaces, if that one
  stopped less than five seconds ago. After a restart, or a longer stop, it starts empty and the
  broker's retained messages fill it. (Found on the reference install with v0.1.0: after a room
  was created, the thermostats stayed unavailable until the bridge's next publication.)
- Contract draft-0 names (`schedule`, `frost_protection`, `frost_protection_temperature`) are read
  as aliases of the current ones.

## Entities

Per thermostat (device named after its bridge name):

| Entity | Source |
|---|---|
| `climate` (only while the thermostat is in no room) | `system_mode`, `running_state`, `local_temperature`; attributes `preset`, `target_temperature` and the setpoints read; preset and setpoint controls where the bridge opens them |
| `number` "Manual setpoint" (in a room or not) | `current_heating_setpoint`; exists once the bridge has opened the setpoint for the thermostat, unavailable while it is closed |
| `sensor` temperature, setpoint, mode | `local_temperature`; setpoint of the current preset; `preset` |
| `sensor` power, energy, voltage, current | `power`, `energy` (kWh, `total_increasing`, usable in the Energy dashboard), `voltage`, `current` |
| `binary_sensor` heating, window, fault | `running_state`, `window_open`, `fault` (names in the `faults` attribute) |

The **setpoint** is the one the thermostat regulates on: `current_heating_setpoint` in `manual`,
`eco_temperature`, `holiday_temperature` or `antifrost_temperature` in those presets, and nothing
in `program` (its target is in no data point) or when off.

The `climate` lists a single HVAC mode, the reported one: on / off is not written. Its other
controls follow the bridge (see "Writes"); with none open it declares no feature and the
interface offers nothing to press. Home Assistant shows a climate's target only with the control
that sets it, hence the `target_temperature` attribute and the setpoint sensor, which stay.

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
| on / off, mode, setpoint | the members' common value; unknown when they differ, or when one member's value is unknown |
| "Thermostats disagree" | on when two members report different on / off, mode or setpoint (an unknown value is not a disagreement); the `differing` attribute names which |
| heating, window, fault | on as soon as one member says so; off only when every member says not; else unavailable |
| power, energy | sums, only when **every** member reports the figure; else unavailable |

A partial energy sum would read as a drop, and an energy counter that drops is read as a reset.
For the same reason, changing a room's members shifts the room's energy counter: for the Energy
dashboard, the per-thermostat energy sensors are the stable choice.

A thermostat in a room keeps its sensors and binary sensors; only its own `climate` is replaced
by the room's.

## Writes

| Key | Values | Offered on |
|---|---|---|
| `preset` | `program`, `manual` (the raw names of the mode sensor; `eco`, `holiday`, `antifrost` are read, never written) | `climate.set_preset_mode` |
| `current_heating_setpoint` | 5–30 °C, step 0.5 (the device takes up to 40; the bridge stops at 30) | `climate.set_temperature`, the "Manual setpoint" `number` |
| the weekly schedule | days described in full | the service `tuya_pilot_wire.set_schedule` ("Weekly schedule" below) |
| everything else (on / off, child lock…) | — | not built |

**Who opens a write: the bridge.** `const.SET_KEYS` is what the Companion can build and check; a
key is published to a thermostat only while that thermostat's bridge publishes, in
`bridge/info` (contract version 5):

```json
"read_only": false,
"writes": {"enabled": true, "keys": ["current_heating_setpoint", "preset"],
           "devices": ["<friendly name>", "..."]}
```

the key in `writes.keys` and the thermostat in `writes.devices`. A version-4 bridge that names a
single `writes.device` is read as a list of one. Anything else — `read_only` true or absent, no
`writes`, a malformed one — opens nothing. The owner's designation of the thermostats, and the
supervised trial of each new write, live on the bridge side; the Companion has no option for it
(the "Write trial" option of 0.2.x is dropped by the entry migration to 1.2).

**A room** offers a control only when it is open for **every** member; a thermostat outside any
room, when it is open for it. A control that closes disappears from the climate; the setpoint
`number` stays, unavailable.

What a write does:

1. checks, for every thermostat concerned, before anything is published: the route is open, the
   thermostat is usable, the value is in bounds (preset: `program` or `manual`), and for a
   setpoint that the thermostat is in `manual` — in `program` the running schedule slot
   overwrites a written setpoint, and the other presets do not keep it (contract §4). A refusal
   here publishes nothing and names the thermostats concerned. To set a room's setpoint, set its
   preset to `manual` first;
2. publishes `{"<key>": <value>, "transaction": <id>}` — one key per command, as the bridge
   requires — on each thermostat's `/set` topic, **one after the other** (the bridge writes and
   reads back one device at a time), each with its own transaction. Two commands to the **same**
   thermostat are at least 10 s apart (`MIN_SET_INTERVAL`, the bridge's limit): a preset then a
   setpoint waits here instead of being refused there. The bridge's other limit, 30 writes an
   hour per thermostat, is not counted here: past it, its refusal is the call's error;
3. waits up to 45 s for each answer on `bridge/response/device/set`; `"status": "ok"` with no
   result `"confirmed": false` is a confirmation. A thermostat refused or not confirmed does not
   stop the others: the call then fails naming each thermostat not confirmed with the bridge's
   reason, and those that were;
4. changes **nothing** in the state shown: the preset and setpoint move when the bridge publishes
   the state the devices confirmed.

For an automation: `climate.set_preset_mode` (`manual`), then `climate.set_temperature`; back with
`climate.set_preset_mode` (`program`). A failed call is an error in the automation's trace.

Entering `manual` restores the setpoint the thermostat keeps for that mode, which can be far from
the one wanted (seen at 21 °C on one thermostat in
[trial 2](validation/2026-11-28-trial-2-preset-and-setpoint.md)). Send the setpoint right after
the preset, and if that call fails, set the preset back to `program` rather than leave the room
heating on the kept value.

## Weekly schedule

The schedule lives in data points only the bridge's **developer channel** reads (contract §5,
version 6). The Companion never asks for it on its own: it shows what the bridge publishes, and
reads or writes it when a service is called.

**Read.** The bridge reads each thermostat's schedule once an hour, with its eco and frost
setpoints, and publishes it in the state object (`tuya.schedule`, `tuya.read.schedule.at`). The
Companion shows it as attributes, kept out of the recorder (a few kilobytes that change rarely):

| Climate | Attributes |
|---|---|
| a thermostat outside any room | `schedule` (`{monday: [{time, temperature}, …], …}`), `schedule_read_at` |
| a room | `schedule`: the days **every** member holds the same; `schedule_differing_days`: the days two members hold differently, and `schedule` then joins `differing` (the room's "Thermostats disagree" sensor turns on) |

A thermostat whose bridge never read the schedule has `schedule: null`, and so has its room: an
unknown member leaves the room's schedule unknown, as for any room value. A change made in the
Tuya app shows within the hour, or at once after `get_schedule` with `refresh`.

**`tuya_pilot_wire.get_schedule`** (`room` or `thermostat`, optional `refresh`): returns the
schedule of each thermostat with when it was read, and for a room the days shared and the days
that differ. With `refresh: true` it sends `bridge/request/schedule/get` for each thermostat and
returns what the bridge read now; refused while the bridge's developer channel is not `online`.

**`tuya_pilot_wire.set_schedule`** — WRITE. Target: `room` (every member) or `thermostat`. The
days, either:

- `days` and `transitions`: the same day for each day named, e.g. a weekend;
- `schedule`: each day its own changes, `{saturday: [...], sunday: [...]}`.

A day is its setpoint changes, **described in full**: the first at `00:00`, times on a
15-minute step, temperatures 5–30 °C by 0.5. The days not given stay as they are on the
thermostat.

```yaml
action: tuya_pilot_wire.set_schedule
data:
  room: Library
  days: [saturday, sunday]
  transitions:
    - {time: "00:00", temperature: 7}
    - {time: "08:00", temperature: 17}
    - {time: "12:00", temperature: 7}
response_variable: written
```

What it does:

1. checks before anything is published: every day is described as above (the same rules as the
   bridge's library), the bridge lists `schedule/set` in `bridge/info.writes.requests` and the
   thermostat in `writes.devices` — for **every** thermostat of a room — and each is usable. A
   refusal publishes nothing and names the day or the thermostats;
2. publishes `bridge/request/schedule/set` `{"device": …, "days": {…}, "transaction": …}` for
   each thermostat, **one after the other**, 10 s apart for the same thermostat (the bridge
   counts a schedule write in its rate limit);
3. waits up to 60 s for each answer (the bridge writes, then reads the schedule back for up to
   30 s). Confirmed means `"status": "ok"`, `confirmed: true`, **and** every day asked found as
   asked in the schedule read back. A thermostat refused or not confirmed does not stop the
   others; the call then fails naming each, with the bridge's reason;
4. returns, by thermostat, `confirmed` and the schedule read back. The attributes follow when
   the bridge publishes the state again (right after the write).

No card or panel edits the schedule in this version: the service, from the Developer tools
("Actions") or a script, is the way to change it, and `get_schedule` the way to read it whole.

## Diagnostics

Downloadable from the integration page. Thermostats and rooms are numbered instead of named; no
device id, IEEE address, gateway id, account, key or address is included. Measured values, modes
and the property names each bridge publishes are kept.
