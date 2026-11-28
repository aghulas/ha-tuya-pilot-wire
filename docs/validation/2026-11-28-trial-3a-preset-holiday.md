# Trial 3a — preset `holiday` through the bridge (2026-11-28)

Status: **run, passed** on one thermostat. The exact operation (holiday, then back to program, on
thermostat A of the reference room) was agreed by the owner before it was sent.

First of the settings trials (bridge contract version 7, §4.1): each further setting is a closed
candidate, opened by `trial_setting` / `trial_device` on one thermostat for its trial, then
proven in the library and opened for every designated thermostat with `write_settings`.

## Setup

- Bridge `tuyapilot2mqtt` 0.5.0 (contract 7), library `pytuya-pilot-wire` 0.5.0, sharing and LAN
  channels online. Options: `trial_setting: preset_holiday`, `trial_device` thermostat A.
  `bridge/info.writes.trial` named that setting and that thermostat; `writes.presets` stayed
  `["manual", "program"]` for every other thermostat.
- Commands published to `<prefix>/<name>/set` by Home Assistant's `mqtt.publish`, with a
  `transaction`. The Companion was not the path written.
- Readers: (a) the bridge's log and state topic (sharing API read-back); (b) the LAN channel,
  which does not return the mode data point (DP 2): it gave the load state only; (c) the owner,
  in the vendor app, during the holiday step.
- Before: thermostat A in `program`, running slot at 5.0 °C, room at 6.0 °C, idle; holiday
  setpoint 5.0 °C. The five other thermostats of the account in `program`.

## Sequence and results

Times are local (UTC+1). "Sent" and "confirmed" are the bridge's log lines.

| Step | Command | Sent | Confirmed | Delay | Bridge state after | LAN | Owner |
|---|---|---|---|---|---|---|---|
| 1 | `{"preset": "holiday"}` | 11:59:21.60 | 11:59:23.91 | 2.3 s | `preset: holiday`, raw `holiday`, room 6.0 °C | idle | "holiday" shown ✓ |
| 2 | `{"preset": "program"}` | 12:46:56.22 | 12:46:58.53 | 2.3 s | `preset: program`, slot 5.0 °C, room 6.5 °C | idle | |

- Two commands, each sent **once**, each confirmed by the bridge's read-back.
- The thermostat stayed in `holiday` for 47 minutes, longer than planned: the owner's check took a
  while, and Home Assistant was restarted meanwhile (by other work), which delayed the return
  command published through it. The bridge, an add-on, was not affected. No heating: the holiday
  setpoint (5.0 °C) was below the room temperature.
- The five other thermostats did not change mode, setpoint or load during the trial.
- The trial options were cleared right after (one add-on restart).

## What the trial showed

- The sharing API takes `mode = holiday` and the device reports it back within one read
  (~2.3 s), like `manual` and `program` (trial 2).
- No data point of the table carries a holiday period, and the thermostat stayed in `holiday`
  until another mode was written: through this route it is an "away until further notice" mode,
  not a dated holiday. Whether the vendor app sets a period of its own was not checked.
- In `holiday` the thermostat follows `holiday_temperature` (DP 24).

## Decision

`mode:holiday` is proven on the sharing API (`pytuya-pilot-wire` route table), and the setting
`preset_holiday` can be opened for the designated thermostats with `write_settings`.
