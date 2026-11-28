# Trials 4a, 4b, 5a, 5b — child lock, window detection, calibration, holiday setpoint (2026-11-28)

Status: **run, all passed** on one thermostat. The four exact operations (each value out, then
back to the value it had) were agreed together by the owner before the first was sent.

Same setup as [trial 3a](2026-11-28-trial-3a-preset-holiday.md): bridge 0.5.0 (contract 7),
thermostat A of the reference room, one setting opened at a time by `trial_setting` /
`trial_device` (one add-on restart each), commands through Home Assistant's `mqtt.publish`, one
key per command. Readers: the bridge's log and state topic (sharing API read-back), the LAN
channel (load state and power: none of these four data points is in a LAN reading), and the owner
in the vendor app at the end. Before: `program`, slot 5.0 °C, room 6.5 °C, idle; child lock
`LOCK`, window detection `OFF`, calibration 0, holiday setpoint 5.0 °C.

## Results

Times are local (UTC+1). "Sent" and "confirmed" are the bridge's log lines; the raw command is the
one the bridge logged.

| Trial | Command | Raw command | Sent | Confirmed | Read back |
|---|---|---|---|---|---|
| 4a | `{"child_lock": "UNLOCK"}` | `child_lock=False` | 13:09:57.90 | 13:10:00.23 | `UNLOCK` |
| 4a | `{"child_lock": "LOCK"}` | `child_lock=True` | 13:10:26.82 | 13:10:29.12 | `LOCK` |
| 4b | `{"window_detection": "ON"}` | `window_check=True` | 13:12:48.10 | 13:12:50.43 | `ON` |
| 4b | `{"window_detection": "OFF"}` | `window_check=False` | 13:13:11.37 | 13:13:13.67 | `OFF` |
| 5a | `{"local_temperature_calibration": -1}` | `temp_correction=-1` | 13:15:22.55 | 13:15:24.88 | `-1` |
| 5a | `{"local_temperature_calibration": 0}` | `temp_correction=0` | 13:16:50.17 | 13:16:52.47 | `0` |
| 5b | `{"holiday_temperature": 5.5}` | `holiday_temp_set=55` | 13:19:06.50 | 13:19:08.79 | `5.5` |
| 5b | `{"holiday_temperature": 5.0}` | `holiday_temp_set=50` | 13:19:27.41 | 13:19:29.73 | `5.0` |

- Eight commands, each sent **once**, each confirmed by the read-back in 2.3 s.
- **The calibration acts on the reported room temperature**: with −1, the next reading of
  `local_temperature` went from 6.5 to 5.5 °C, and back to 6.5 °C after the return to 0.
- No heating during these trials; the thermostat stayed in `program`. The five other thermostats
  did not change mode, setpoint or any of these settings.
- The trial options were cleared right after (one add-on restart).

## Decision

`child_lock`, `window_detection`, `temperature_correction` (`local_temperature_calibration`) and
`holiday_setpoint` (`holiday_temperature`) are proven on the sharing API, and their settings can
be opened for the designated thermostats with `write_settings`.
