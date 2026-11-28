# Trials 3b and 3c — preset `antifrost` (refused) and `eco` (passed) (2026-11-28)

Same setup as [trial 3a](2026-11-28-trial-3a-preset-holiday.md): bridge 0.5.0 (contract 7),
thermostat A of the reference room, commands through Home Assistant's `mqtt.publish`, one key per
command; readers: the bridge's log and state topic (sharing API), the LAN channel (load state and
power; it does not return the mode), the owner. Each operation was agreed by the owner before it
was sent. Before each trial: `program`, running slot 5.0 °C, room 6.5 °C, idle.

## 3b — `{"preset": "antifrost"}` (raw mode `hors`): refused by the sharing API

Option `trial_setting: preset_antifrost`. Times are local (UTC+1).

| Step | Command | Sent | Answer | Bridge state after |
|---|---|---|---|---|
| 1 | `{"preset": "antifrost"}` | 12:52:45.77 (`mode='hors'`) | error, 0.23 s later, no read-back | unchanged: `program`, idle |

- The gate let the command through (the route was open for this thermostat) and it was sent
  **once**; the sharing API answered with an error within 0.23 s, before any read-back, and the
  thermostat did not change (the next reads and the LAN load state agree). The text of the error
  went to the non-retained response topic, which was not being listened to at that moment.
- **Conclusion**: the sharing API does not take the frost-protection value the devices report
  outside their declared mode list. `preset_antifrost` **stays closed**: frost protection can be
  entered from the vendor app or the device, and the bridge publishes it when read
  (`preset: antifrost`), but it cannot be written through this route. No step 2 was needed.

## 3c — `{"preset": "eco"}` then `{"preset": "program"}`: passed

Option `trial_setting: preset_eco`.

| Step | Command | Sent | Confirmed | Delay | Bridge state after | LAN |
|---|---|---|---|---|---|---|
| 1 | `{"preset": "eco"}` | 12:56:37.63 | 12:56:39.95 | 2.3 s | `preset: eco`, `current_heating_setpoint` **14.0** | 12:57:47: heating, 1516 W |
| 2 | `{"preset": "program"}` | 12:58:10.54 | 12:58:12.88 | 2.3 s | `preset: program`, slot 5.0 °C | 12:58:48: idle, 0 W |

- Two commands, each sent once, each confirmed by the read-back; the LAN channel, independent of
  the sharing API, saw the radiator start heating in `eco` and stop after the return to
  `program`. Heating lasted under two minutes. The owner did not check the app during the short
  `eco` step (kept short on purpose, as the room was below the eco setpoint).
- **In `eco`, DP 50 (`temp_set`, published as `current_heating_setpoint`) reports the eco
  setpoint** (14.0 °C here), as in `program` it reports the running slot's: the thermostat
  regulates on it. The eco setpoint itself (DP 117) has no write route through the sharing API.
- The five other thermostats did not change.

## Decision

- `mode:eco` is proven on the sharing API, and `preset_eco` can be opened with `write_settings`.
  A reader offering `eco` should show the eco setpoint the thermostat then follows (reported in
  `current_heating_setpoint`), which only the app or the device can change.
- `mode:hors` (`preset_antifrost`) stays a closed candidate, with this trial as the reason.
