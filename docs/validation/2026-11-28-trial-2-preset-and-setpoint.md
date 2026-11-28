# Trial 2 — preset and manual setpoint through the bridge (2026-11-28)

Status: **run, passed** on the two thermostats of one room. Each sequence was agreed by the
owner before it was sent, and each step was read back before the next one.

## Setup

- Bridge `tuyapilot2mqtt` 0.3.0 (contract 5), library `pytuya-pilot-wire` 0.3.0, sharing and LAN
  channels online. `bridge/info`: `read_only: false`, `writes.keys` `["current_heating_setpoint",
  "preset"]`, `writes.devices` the two thermostats of the room, and no other.
- Companion 0.3.1 loaded. It was **not** the path written: its room `climate` fans a command out to
  both members, and this trial wanted one thermostat at a time. Each command was published to
  `<prefix>/<name>/set` by Home Assistant's `mqtt.publish` service, one key per command, with a
  `transaction`.
- Readers: (a) the bridge's log (`WRITE sent … once`, `WRITE answered: confirmed`) and its state
  topic; (b) an independent LAN reader of the same gateway, which does not use the sharing API
  (local read only); (c) the owner, in the vendor app, at the steps marked ✓.
- Before the trial: both thermostats in `program`, room at 7.5 °C, not heating. Thermostat A read
  a manual setpoint of 5.0, thermostat B 9.0, in both readers.

## Sequence (same for each thermostat, A then B)

1. `{"preset": "manual"}`
2. `{"current_heating_setpoint": 9.5}`
3. `{"current_heating_setpoint": 9.0}`
4. `{"preset": "program"}`

Stop rule agreed beforehand: at any disagreement between readers, any bridge error, or any other
thermostat changing, send `preset: program` to the thermostat on trial and stop. It was not used.

## Results

Times are UTC. "Sent" and "confirmed" are the bridge's log lines; the delay is between them.

| Thermostat | Step | Sent | Confirmed | Delay | LAN reader after the step | Owner |
|---|---|---|---|---|---|---|
| A | 1 `manual` | 03:44:20.11 | 03:44:22.40 | 2.3 s | `manual`, setpoint 9.0, idle | |
| A | 2 9.5 °C | 03:44:55.39 | 03:44:57.70 | 2.3 s | `manual`, 9.5, heating ~1.57 kW | ✓ |
| A | 3 9.0 °C | 03:46:49.61 | 03:46:51.90 | 2.3 s | `manual`, 9.0, heating | |
| A | 4 `program` | 03:47:08.12 | 03:47:10.43 | 2.3 s | `program`, 5.0, idle | ✓ |
| B | 1 `manual` | 03:48:48.96 | 03:48:51.27 | 2.3 s | `manual`, setpoint **21.0**, idle | |
| B | 2 9.5 °C | 03:49:17.58 | 03:49:19.91 | 2.3 s | `manual`, 9.5, heating ~1.60 kW | ✓ |
| B | 3 9.0 °C | 03:51:25.25 | 03:51:27.54 | 2.3 s | `manual`, 9.0, heating | |
| B | 4 `program` | 03:51:44.88 | 03:51:47.17 | 2.3 s | `program`, 5.0, idle | ✓ |

- Eight commands, each sent **once**, each confirmed by the bridge's read-back (sharing API) and
  matched by the LAN reader; the owner saw the same mode and setpoint in the vendor app at each
  ✓ step.
- The bridge's state topic, read after each step, carried the read-back value with
  `tuya.read.<property>.at` at the read-back time. The response topic was not captured (the
  listener timed out); the log lines above are the bridge's answer.
- The other four thermostats of the account (two rooms) did not change mode, setpoint or load
  during the trial. The member not on trial did not change either.
- Heating: about 2 min 15 s on A and 2 min 30 s on B; both radiators stopped on the return to
  `program` (the running slot's setpoint is below the room temperature).
- `bridge/info` unchanged at the end; no error in the bridge's log.

## What the trial showed

- **Entering `manual` restores the setpoint the thermostat keeps for that mode**, which is not
  the value read in `program`: A went from 5.0 to 9.0, B from 9.0 to **21.0**, before any setpoint
  was sent. Both readers agreed. A reader that switches to `manual` and writes its setpoint later
  can make the room heat on that kept value in between; a reader that writes nothing (or whose
  write fails) leaves it there. The Companion's order (preset, then setpoint, one command after
  the other) and a fallback to `program` when the setpoint is not confirmed cover this. After the
  trial both thermostats keep 9.0 for `manual`.
- **The value read in `program` is not stable.** Data point 50 read 5.0 on both thermostats after
  the return to `program`, where B had read 9.0 before the trial. Nothing is derived from it; the
  contract already says the `program` target is in no data point.
- **Transient LAN reads around a load change**, not related to the writes: the first LAN read
  after A started heating gave 51 V and 352 W (next read: 233 V, 1.57 kW); the first one after it
  stopped gave 6.5 A, 0 W and still "heating" (next read: idle). The bridge publishes what it
  reads; one pass later the state is consistent.
- The rate limit (10 s between two commands to a thermostat) was never reached: the steps were
  20 s to 2 min apart.

## Routes after this trial

- `preset` `manual` / `program`, sharing API, through the bridge: **proven on two thermostats**.
- `current_heating_setpoint` in `manual`, sharing API, through the bridge: **proven on two
  thermostats**.
- Not tried here: the Companion's room fan-out (`climate.set_preset_mode`,
  `climate.set_temperature` on the room). It sends the same commands, one member after the other.
