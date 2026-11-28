# Parity between the two bridges (milestone M5)

Status: **written against synthetic frames, not checked on a device yet** (2026-11-28). The
right-hand column is what Zigbee2MQTT would publish with the external converter of
[`zigbee2mqtt/`](../zigbee2mqtt/), the left-hand one what `tuyapilot2mqtt` publishes today
([contract](https://github.com/aghulas/tuyapilot2mqtt/blob/main/docs/mqtt-contract.md) version
5). The on-site trial that checks it is [`z2m-trial-procedure.md`](z2m-trial-procedure.md).

Goal of M5: a thermostat moved from the Tuya gateway to the Zigbee coordinator keeps its
entities, its room and its schedule in the Companion. Short answer: **its entities and its room,
yes** (built and tested); its readings, **mostly** (gaps below); **its schedule stays in the
device**, but reading it on Zigbee2MQTT is not proven; **no write** goes through Zigbee2MQTT.

## Topics

| Topic | `tuyapilot2mqtt` | Zigbee2MQTT + converter | Companion |
|---|---|---|---|
| `bridge/state` | `{"state": "online"}`, last will | same | same rule |
| `bridge/info` | versions, channels, `read_only`, `writes` | versions, `config` (with the network key: never kept) | keeps versions only; **no `read_only: false` → nothing opened** |
| `bridge/devices` | supported thermostats only | every device, coordinator included | keeps `TS0601` + manufacturer ending in `_fu1bfwza` |
| `<name>` | the last value read of each property; absent until read | the **cached** state: every property ever reported, merged | reads the object as given |
| `<name>/availability` | read < 10 min and online for the account | only when `availability` is enabled in Zigbee2MQTT (mains devices: 10 min without a message) | without the topic, the thermostat counts as online |
| `<name>/set` | `preset`, `current_heating_setpoint` on designated thermostats | refused: the converter has no `toZigbee` | never published to Zigbee2MQTT (closed) |
| `bridge/response/device/set` | every `/set` answered, after read-back | none for `/set` | n/a |
| `bridge/request/schedule/*` | contract §5 | none | n/a |

## Device descriptor and identity

| Field | `tuyapilot2mqtt` | Zigbee2MQTT |
|---|---|---|
| `friendly_name` | the name in the Tuya app | the IEEE address until renamed in Zigbee2MQTT |
| `ieee_address` | `0x` + the gateway's node id, lower case, when it is an EUI-64 | `0x…`, lower case |
| `tuya.dev_id` | yes | — |
| `model_id` / `manufacturer` | — | `TS0601` / `_TZE204_fu1bfwza` (interview) |
| `definition.model` | `TS0601_fu1bfwza` | `TS0601_fu1bfwza` (the converter's) |
| `type` | `EndDevice` | `Router` |

The Companion's key is `tuya.dev_id` when present, else the IEEE address; every pair `(IEEE,
dev_id)` it sees is stored (`identities` in its storage) and an IEEE address that comes alone
later resolves to the same key. Unique ids, the device, the room membership and the entity ids
all hang on that key, so **they do not move**. The way back is covered too: a thermostat
re-paired to its Tuya gateway may get a **new** device id, but keeps its IEEE address (the
hardware's); a known IEEE address wins over a new device id, which is remembered as an alias of
the key (`aliases` in the storage) for a later listing that gives the device id alone. Precondition: the Companion must have seen the
thermostat's `ieee_address` from the Tuya bridge at least once before the move (bridge 0.1.1 and
later publish it; diagnostics say `"has_ieee_address": true`). Without it, the Zigbee2MQTT
listing is a new thermostat, outside any room
(`test_identity_needs_the_ieee_address_seen_on_the_tuya_bridge`).

What does change: the Home Assistant **device name** follows the bridge's friendly name at the
next start, unless renamed by the user in Home Assistant. Give the device the same friendly name
in Zigbee2MQTT as in the Tuya app (the procedure does).

### Listed by both bridges at once

During the move, and during a rollback, both bridges can list the thermostat for a while: the
Tuya bridge until the account drops the removed sub-device, Zigbee2MQTT until the device is
removed there. The Companion shows it from **one** bridge only:

- the bridge that held it keeps it while it is usable there (bridge online, device not offline);
- the other listing is a *shadow*: its topics are read, nothing of it is shown, nothing is
  written through it;
- the shadow takes over as soon as the holder is not usable and the shadow is, or at once when
  the holder stops listing it (with the state the shadow had already received);
- it never flips back while the new holder stays usable.

Diagnostics show a `shadow` (its bridge, online, IEEE known) on the thermostat while it lasts.
Tests: [`tests/test_bridge_move.py`](../tests/test_bridge_move.py).

## State properties

| Property | `tuyapilot2mqtt` (source) | Zigbee2MQTT + converter (DP) | Gap |
|---|---|---|---|
| `local_temperature` | DP 16, sharing API | DP 16 ÷ 10 | none |
| `current_heating_setpoint` | DP 50, sharing API | DP 50 ÷ 10 | none |
| `system_mode` | DP 1 | DP 1 bool → `heat` / `off` | none |
| `preset` | DP 2 raw string → `program`, `manual`, `eco`, `holiday`, `antifrost` (`hors`) | DP 2 is an **enum index**; the index ↔ mode table is not established, so **no `preset`**; the raw index is `mode_index` | **Gap 1.** Until the table is measured on site, the mode sensor, the climate's preset and the room's mode are unknown on Zigbee2MQTT. The setpoint sensor too (it depends on the preset) |
| `running_state` | current > 0 (LAN), else DP 124 `work_state` | current > 0 (DP 102); DP 124 published raw as `work_state_index` | **Gap 2.** Same rule; whether the device reports a current of 0 when it stops heating is to check |
| `power` | voltage × current, 0 when idle | same | none, if gap 2 closes |
| `voltage`, `current` | DP 101 ÷ 10, DP 102 mA; **absent when idle** | same conversions; **kept in the cached state when idle** | **Gap 3.** On Zigbee2MQTT the last heating voltage stays shown while idle (`current` reads 0 if reported) |
| `energy` | DP 107 ÷ 10, LAN | DP 107 ÷ 10 | none; the first Zigbee value must continue the Tuya one (procedure, step 6) |
| `window_open` | DP 17 `close` / `open` | DP 17 index 0 / 1, assumed in the declared order | to check (procedure) |
| `window_detection` | DP 29 | DP 29 → `ON` / `OFF` | none |
| `child_lock` | DP 39 | DP 39 → `LOCK` / `UNLOCK` | none |
| `local_temperature_calibration` | DP 19 | DP 19, signed | none |
| `holiday_temperature` | DP 24 | DP 24 ÷ 10 | none |
| `eco_temperature`, `antifrost_temperature` | DP 117 / 116, developer API or LAN | DP 117 / 116 ÷ 10, when the device reports them | to check: reported over Zigbee? |
| `temperature_sensibility` | announced, not published | DP 103 ÷ 10 | Zigbee2MQTT publishes more; the Companion ignores it |
| `fault` | DP 20 bitmap → `e1`, `e2`, `e3`, `bit_<n>` | same | none |
| `last_seen` | always | only with Zigbee2MQTT's `advanced.last_seen` | not read by the Companion |
| `tuya` (raw mode, `read` sources) | yes | — (`mode_index`, `work_state_index` instead) | not read by the Companion |
| `linkquality` | — | yes | ignored |
| `schedule_<day>` | — (schedule through `bridge/request/schedule/get`, §5) | DP 125–152, `"HH:MM/°C …"` per day, **if** the device reports them | **Gap 4**, below |

**Reading rule difference.** The contract says "a property absent is unknown"; Zigbee2MQTT never
drops a property once reported, it republishes its cache. The Companion's rule is unchanged (it
reads the object it is given), so on Zigbee2MQTT a value is "the last one reported" rather than
"the last one read": availability is what says the thermostat stopped talking.

## Schedule

The weekly schedule is **held by the thermostat** (DP 125–152) and does not move with the bridge:
on Zigbee2MQTT it keeps heating on the same programme, provided its clock is right (the converter
answers the device's time request, `time_start` 1970 as the nearest upstream definition; the
procedure checks the clock shown).

Reading it is another matter (**gap 4**): the gateway does not return those data points on a LAN
read, and nothing shows whether the device reports them over Zigbee unasked. The converter decodes
them when they come, a day once its four parts are known. The Companion does not read a schedule
from Zigbee2MQTT yet: the schedule work in progress (`bridge/request/schedule/get` on the Tuya
bridge) should also read `schedule_<day>` from a Zigbee2MQTT state once gap 4 is closed. Writing
it through Zigbee2MQTT is not built.

## Writes

None goes through Zigbee2MQTT, by three locks: the converter has no `toZigbee`; Zigbee2MQTT's
`bridge/info` has no `read_only: false`, so `supports_set` is false for every thermostat it holds;
a thermostat shown from the Tuya bridge is written only there. Opening one later needs, in this
order: the index table (gap 1) for `preset`; a `to` conversion in the converter for one key; a
way for the Companion to know the key is open on Zigbee2MQTT (an option per thermostat, since
Zigbee2MQTT carries no `writes`); confirmation by reading the state back (Zigbee2MQTT answers
nothing on `bridge/response/device/set`); and a supervised trial recorded in
[`validation/`](validation/).

## What the Companion does, in short

| Need | Status |
|---|---|
| Recognise the thermostat on Zigbee2MQTT (`TS0601`, `…_fu1bfwza`) | built (M3) |
| Same key, entities, device, room after the move (`dev_id` ↔ `ieee_address`) | built (M3), tested again here |
| Same key after the way back with a new device id | **built in this change** |
| One copy shown while both bridges list it, no flip-flop | **built in this change** |
| Diagnostics of a move in progress (`shadow`) | **built in this change** |
| No write through Zigbee2MQTT | built (by `bridge/info`), tested here |
| Preset on Zigbee2MQTT | waits for the index table (on site) |
| Schedule read on Zigbee2MQTT | waits for gap 4 (on site), then the schedule work |
