# On-site trial: one thermostat from the Tuya gateway to Zigbee2MQTT, and back

Status: **written, not run; postponed** (2026-11-28) until new Zigbee coordinator dongles are
installed on site. Done that day, remotely: B1 (backup), B2 (every thermostat's IEEE address is
published by the bridge), B4 and B5 (state and schedule of the chosen thermostat recorded), B6,
and B8 (the converter saved and loaded through Zigbee2MQTT's `bridge/request/converter/save`,
no restart needed; it stays loaded). Nothing else. For the owner, on site. Nothing here is done remotely
or unattended: pairing needs a hand on the thermostat. What the trial checks is listed in
[`z2m-parity.md`](z2m-parity.md); its record goes to [`validation/`](validation/).

Read only on the Zigbee side: the converter writes nothing ([`zigbee2mqtt/`](../zigbee2mqtt/)),
the Companion offers no control for a thermostat held by Zigbee2MQTT. The only frames it sends
are Tuya's standard ones (the time the device asks for, the configure sequence).

## What the trial must show

1. The interview gives `TS0601` and a manufacturer name ending in `_fu1bfwza` (and which prefix:
   `_TZE204_` or `_TZE284_`); Zigbee2MQTT says *supported*, model `TS0601_fu1bfwza`.
2. The thermostat **keeps its entities and its room** in the Companion (same entity ids), its
   values match its own display, and energy continues the Tuya figure.
3. The **DP 2 index of each mode** (fills `MODE_BY_INDEX` in the converter, gap 1 of the parity
   table), and of the load state on DP 124.
4. Whether the device reports a current of 0 when it stops heating (gap 2), and whether it reports
   its weekly schedule over Zigbee (gap 4).
5. The device clock is right (the schedule depends on it) and the schedule is followed.
6. The way back works, with entities and room kept, whatever device id the Tuya account gives it.

## Choosing the thermostat and the slot

- **One** thermostat, in a room where an afternoon on its schedule is harmless. While it is on
  Zigbee2MQTT, the Tuya bridge cannot write it and **its room loses its preset and setpoint
  controls** (a room offers a write only when it is open for every member). Better not one of
  the thermostats the bridge has designated for writes (`write_devices`), so that the bridge's
  designation does not change.
- A slot with nobody in the room, 2 h on site for the outward trip and the checks, the same again
  for the way back if done on the same day. Between the two, 24 to 48 h on Zigbee2MQTT tell
  whether the schedule is followed.

## Before (remote, the day before)

| | Check | Where | Expected |
|---|---|---|---|
| B1 | A Home Assistant backup | `ha_sauvegarde_preparer` (owner's agreement) | done |
| B2 | The Companion knows the thermostat's IEEE address | Companion diagnostics: the thermostat's `has_ieee_address` | `true` (else stop: the move would make a new device) |
| B3 | The Companion reads `zigbee2mqtt` | integration options, bridge prefixes | `zigbee2mqtt` listed |
| B4 | Record the thermostat's state | Companion entities: temperature, mode, manual setpoint, energy, child lock, window detection, correction | written in the record |
| B5 | Record its weekly schedule | the bridge's developer channel (schedule read) or the vendor app | the 7 days, written in the record (private copy: it is site data) |
| B6 | Zigbee2MQTT healthy, on its usual version | add-on page; `zigbee2mqtt/bridge/state` | `online`, 2.14.x |
| B7 | Availability is on in Zigbee2MQTT | its settings, *Availability* (do not open or copy `configuration.yaml`: it holds the network key) | on; else turn it on in the frontend |
| B8 | The converter in place | publish `{"name": "tuya_pilot_wire_fu1bfwza.js", "code": …}` on `zigbee2mqtt/bridge/request/converter/save` (Zigbee2MQTT saves and loads it, no restart; `bridge/converters` then lists it), or copy `zigbee2mqtt/tuya_pilot_wire_fu1bfwza.js` of this repository to `/config/zigbee2mqtt/external_converters/` on the Pi, restart the add-on | the log says the external converter is loaded; the Danfoss heads still report |

B8 changes the Pi: it is done with the owner's agreement, and undone at R6.

## Outward: from the Tuya gateway to Zigbee2MQTT

| | Step | Expected |
|---|---|---|
| A1 | Note the time; read the thermostat's display (mode, setpoint, room temperature, clock) | in the record |
| A2 | In the Smart Life app: the thermostat → edit → **Remove device** (not *Disconnect and wipe data*) | gone from the app; within 10 min the Tuya bridge marks it offline, then drops it from `bridge/devices` |
| A3 | Zigbee2MQTT frontend: *Permit join* on the coordinator (or the router nearest the thermostat), the default 254 s | join open |
| A4 | Put the thermostat in pairing mode as its manual says | it leaves the gateway's network and starts looking |
| A5 | Interview in Zigbee2MQTT | `TS0601`, `_TZE20x_fu1bfwza`, Router, mains, *supported*, model `TS0601_fu1bfwza`. Note the exact manufacturer name. **Close the join** |
| A6 | Rename it in Zigbee2MQTT to its name in the Tuya app (the Home Assistant device name follows it) | topic `zigbee2mqtt/<name>` |
| A7 | Zigbee2MQTT state within a few minutes | `local_temperature`, `current_heating_setpoint`, `system_mode`, `mode_index`, matching the display |
| A8 | The Companion | the same entities (same ids) now read Zigbee2MQTT; diagnostics: thermostat on `zigbee2mqtt`, `shadow` gone once the Tuya bridge dropped it; the room's temperature includes it; its mode and preset unknown (gap 1, expected) |
| A9 | Energy | the Zigbee figure ≥ the last Tuya figure (B4). Lower: note it, the Energy dashboard will see a reset |
| A10 | Clock on the display | right to the minute. Wrong by a fixed offset: note it (the converter's `time_start` option, 1970 or 2000, is the next thing to try; not on this trial) |

Zigbee2MQTT's own Home Assistant discovery also creates entities for it under the MQTT
integration; they can be disabled, the Companion does not use them.

## Measurements on Zigbee2MQTT (keypad only, no network write)

| | Step | Record |
|---|---|---|
| M1 | On the thermostat's keypad, set each mode in turn: manual, program, eco, holiday, frost protection if the keypad offers it; wait 30 s after each | `mode_index` for each mode |
| M2 | In manual, raise the setpoint on the keypad above the room temperature until it heats, then back below | `current`, `power`, `running_state`, `work_state_index` while heating and after; whether `current` goes back to 0 |
| M3 | Put the mode and setpoint back as at A1 | display as at A1 |
| M4 | Watch the state for 15 min | do `schedule_<day>` properties appear? (gap 4) |
| M5 | Over the next 24 to 48 h, at two schedule changes | `running_state` / `current_heating_setpoint` change at the times of B5 |

Back home: the index table goes into the converter (`MODE_BY_INDEX`, `HEATING_BY_WORK_STATE_INDEX`)
in a change of its own, with this record.

## Way back: from Zigbee2MQTT to the Tuya gateway

| | Step | Expected |
|---|---|---|
| R1 | Zigbee2MQTT frontend: the thermostat → *Remove* (*force remove* if it does not answer) | gone from `zigbee2mqtt/bridge/devices`; in the Companion the thermostat is unavailable |
| R2 | Smart Life app: the gateway → *Add sub-device*; put the thermostat in pairing mode | it appears in the app |
| R3 | Give it its former name in the app, **exactly** (the bridge's write designation and topic use it) | `tuyapilot2mqtt/<name>` |
| R4 | The Tuya bridge | lists it again (a new device id is possible), state and energy read; if energy stays absent, the LAN channel does not know the new sub-device: the bridge's local keys file has to be refreshed (bridge documentation) |
| R5 | The Companion | the same entities and the same room (the IEEE address keeps the key even with a new device id); diagnostics: on `tuyapilot2mqtt`, no `shadow` |
| R6 | Its schedule | compare with B5. Different: restore it through the bridge's proven schedule route, with the owner's agreement on the exact schedule (supervised write) |
| R7 | The converter | leave it in place, or remove it from `external_converters/` and restart Zigbee2MQTT |

## Stop and roll back at once if

- the interview does not give `TS0601` / `…_fu1bfwza`, or Zigbee2MQTT says *unsupported* after
  B8;
- the radiator does not follow the thermostat's display, or the display shows an error;
- the Danfoss heads on the same Zigbee network stop reporting;
- the Companion creates a **new** device for the thermostat instead of keeping the old one (B2
  should have prevented it): do not delete anything, roll back, and keep the diagnostics.

## Record

`docs/validation/<date>-m5-zigbee2mqtt-trial.md`, restated generically (no device id, IEEE
address, name of room or site): versions (Zigbee2MQTT, converter commit, Companion, bridge), the
manufacturer prefix, the index tables, what each gap gave, the times of A2–A8 and R1–R5, and
whether the entities and the room were kept both ways.
