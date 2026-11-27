# Trial 1 — manual setpoint through the Companion: protocol

Status: **prepared, not run.** Nothing has been written to a thermostat. This is the protocol
the owner agrees to before the trial; its record will be a dated file next to this one.

## The operation

One key, `current_heating_setpoint` (data point 50, the setpoint of the `manual` preset), on
**one** thermostat the owner designates, raised by 0.5 °C and put back.

| | |
|---|---|
| Path | Home Assistant `number` → `<prefix>/<name>/set` → bridge → Tuya device-sharing API → gateway → thermostat |
| Route | sharing API, already proven outside this project (2026-10-31, applied and reported back in under 20 s). What is on trial is the chain above it: Companion, contract, bridge write gate |
| Preset during the trial | the thermostat's current one. In `program` the device stores the manual setpoint and does not regulate on it: the heating is not affected. In `manual` the room setpoint moves by 0.5 °C for the length of the trial |
| Refused beforehand | a thermostat in frost protection (stored and not applied, and the mode is outside the declared list) |

## Preconditions

1. Bridge with the sharing channel connected and its write gate, `bridge/info.read_only` false,
   accepting only `current_heating_setpoint`, and answering each command on
   `bridge/response/device/set` with the command's `transaction`, after reading the device back.
2. Companion 0.2.0 or later loaded; the thermostat designated in the options ("Write trial").
   The "Manual setpoint" number then appears on that thermostat and on no other.
3. The owner's agreement on: the thermostat, the two values, the time.
4. The thermostat online, its manual setpoint read (`S0`) and equal in every reader.

## Steps

| # | Action | Expected |
|---|---|---|
| 1 | Note `S0` in the Companion, in a LAN reader that is not the bridge, and in the vendor app | three equal values |
| 2 | Set the number to `S0 + 0.5` | the service call returns without error only after the bridge answered `ok` |
| 3 | Watch the number | it shows `S0` until the bridge publishes the state, then `S0 + 0.5`; `tuya.read.current_heating_setpoint.at` is later than step 2 |
| 4 | Read the independent LAN reader, then the vendor app or the thermostat's own menu | `S0 + 0.5` in both |
| 5 | Check the other five thermostats | manual setpoints unchanged |
| 6 | Set the number back to `S0` | as steps 2 to 4, with `S0` |
| 7 | Refusals, nothing may reach the device: a value off the step (through the service), a value above the maximum, a command to another thermostat | each refused by the Companion; no `/set` published (bridge log) |
| 8 | Designate no thermostat in the options | the number is gone |

## Stop conditions

Stop and restore `S0` from the vendor app if: the bridge answers `ok` and an independent reader
disagrees after two minutes; another thermostat changes; the thermostat changes mode or on / off
state; the bridge or the sharing session reports an error after the write.

## What the trial opens

If every step holds: `current_heating_setpoint` moves from `TRIAL_SET_KEYS` to `OPEN_SET_KEYS`
in the change that adds the record, and the room `climate` gets its setpoint (fan-out to the
members, each confirmed separately) as the next piece of M4. If not: the key stays closed and the
record says what failed.
