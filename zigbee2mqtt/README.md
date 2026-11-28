# Zigbee2MQTT external converter

For the Tuya "FP Thermostat", a pilot-wire thermostat for electric radiators: Zigbee model
`TS0601`, manufacturer `_TZE204_fu1bfwza` (Tuya product id `fu1bfwza`). Zigbee2MQTT has no
definition for it upstream ([`docs/device.md`](../docs/device.md)).

**Read only.** The definition has no `toZigbee` converter: every `/set` is refused by
Zigbee2MQTT and nothing is written to the device. Writes are added one key at a time, after a
supervised trial on real hardware.

**Not run on a device yet.** Tested on synthetic Tuya frames only; the on-site trial is
[`docs/z2m-trial-procedure.md`](../docs/z2m-trial-procedure.md). Until it has run, the mode is
published as its raw index (`mode_index`) and `preset` is absent.

## Install (Zigbee2MQTT 2.x)

1. Copy [`tuya_pilot_wire_fu1bfwza.js`](tuya_pilot_wire_fu1bfwza.js) to the
   `external_converters/` folder of Zigbee2MQTT's data directory (the Home Assistant add-on:
   `/config/zigbee2mqtt/external_converters/`).
2. Restart Zigbee2MQTT; its log says the converter is loaded.
3. Pair the thermostat. It shows as supported, model `TS0601_fu1bfwza`.

## What it publishes

The property names of the [MQTT contract](https://github.com/aghulas/tuyapilot2mqtt/blob/main/docs/mqtt-contract.md)
of `tuyapilot2mqtt`, so that the [Companion](../README.md) sees the same thermostat on either
bridge. Table and gaps: [`docs/z2m-parity.md`](../docs/z2m-parity.md).

| Property | Data point |
|---|---|
| `local_temperature`, `current_heating_setpoint` | 16, 50 (÷ 10 °C) |
| `system_mode` (`heat` / `off`) | 1 |
| `mode_index` (raw), `preset` once the index table is measured | 2 |
| `window_open`, `window_detection`, `child_lock` | 17, 29, 39 |
| `local_temperature_calibration` | 19 |
| `fault` (`e1`, `e2`, `e3`) | 20 |
| `holiday_temperature`, `antifrost_temperature`, `eco_temperature` | 24, 116, 117 (÷ 10 °C) |
| `temperature_sensibility` | 103 (÷ 10 °C) |
| `voltage`, `current`, `power`, `running_state` | 101 (÷ 10 V), 102 (mA); power = V × A, heating = current > 0 |
| `energy` | 107 (÷ 10 kWh) |
| `work_state_index` (raw) | 124 |
| `schedule_monday` … `schedule_sunday` (`"HH:MM/°C"` at each change) | 125–152, a day once its four parts are reported |

## Tests

```bash
cd zigbee2mqtt && npm ci && npm test
```

`zigbee-herdsman-converters` is pinned to the version of Zigbee2MQTT 2.14.3.
