# The device (milestone M0)

Status: **identified** (2026-11-27), read-only. Nothing was re-paired, reset or written.

## Answer in short

| Question | Answer | How sure |
|---|---|---|
| Radio between thermostat and gateway | **Zigbee** (Tuya `TS0601`, data points tunnelled in the manufacturer cluster `0xEF00`) | Established, see "Evidence" |
| Zigbee model id | `TS0601` | From a public interview of the same product; not read on the reference install |
| Zigbee manufacturer name | `_TZE204_fu1bfwza` | Same. The prefix (`_TZE204_`, possibly `_TZE284_` on another module batch) is confirmed only by an interview on a Zigbee coordinator |
| Zigbee device type | Router, mains powered | Public interview |
| Does Zigbee2MQTT define it? | **No.** `zigbee-herdsman-converters` has no entry for `fu1bfwza` (checked on `master`, 2026-11-25). An external-converter request was closed as not planned | Established |
| Consequence | A converter is part of the project (M5). The contract's property names are fixed on the vocabulary Zigbee2MQTT already uses for the nearest device, see "Property names" | Decision |

## Evidence

1. **The gateway reports the thermostats as sub-devices with an EUI-64.** Through the Tuya
   developer API (device details and the gateway's sub-device list, read only), each of the six
   thermostats of the reference install has `sub: true`, product id `fu1bfwza`, model `pl_01`, and
   a `node_id` / `uuid` of 16 hexadecimal digits whose first three bytes are the `a4:c1:38`
   prefix carried by Tuya's Zigbee modules. A Bluetooth or Wi-Fi device would carry a 6-byte
   address. The gateway is a `GW002` (category `wg2`), a multi-protocol gateway with a Zigbee
   radio.
2. **A unit of the same product was interviewed by Zigbee2MQTT.** A public issue
   ([Koenkk/zigbee2mqtt#29764](https://github.com/Koenkk/zigbee2mqtt/issues/29764), 2025-11-22,
   Zigbee2MQTT 2.6.3) carries the database entry of a thermostat paired directly to a
   coordinator: model id `TS0601`, manufacturer name `_TZE204_fu1bfwza`, type Router, power
   source mains, endpoint 1 with input clusters `genBasic`, `genGroups`, `genScenes` and
   `0xEF00` (61184), endpoint 242 (Green Power). For a Tuya Zigbee product the suffix of the
   manufacturer name is the cloud product id, which is the one this project reads: `fu1bfwza`.
3. **A second public source** pairs the same product id with the same fingerprint: a user's
   Zigbee2MQTT configuration with an external converter for `_TZE204_fu1bfwza`, whose notes show
   the developer-API record of their unit (`product_id: fu1bfwza`, `product_name: FP Thermostat`,
   `model: pl_01`, `sub: true`, an EUI-64 as `uuid`).

What is **not** read on the reference install: the manufacturer name and model id as the devices
announce them. The Tuya APIs do not expose the Zigbee Basic cluster. See "On-site check".

## Zigbee2MQTT support

- **Upstream**: none. Searching `zigbee-herdsman-converters` for `fu1bfwza` returns nothing.
- **Nearest upstream definition**: `_TZE204_3regm3h6` ("Smart thermostat for electric radiator
  with pilot wire", white labels THALEOS TH-P1Z, RKHK TH-P0Z, MAZDA MZTE1Z). Same family, another
  product: its mode list (comfort, eco, antifrost, off, comfort −1, comfort −2, program, manual)
  is not this thermostat's (eco, holiday, program, manual, plus an undeclared frost-protection
  value). It cannot be reused by adding a fingerprint.
- **External converters in the wild**: the issue above reuses another thermostat's definition
  and was never completed; the user configuration in point 3 maps the data points listed below
  and replaces the thermostat's own regulation with a software hysteresis loop. Neither is a base
  for this project: the Companion must show what the device does, not regulate in its place.

So M5 needs **a converter of our own**, written against the data-point table of
`pytuya-pilot-wire` and proposed upstream once one thermostat has run on it. Written
2026-11-28, read only: [`zigbee2mqtt/`](../zigbee2mqtt/).

## Data points over Zigbee

The data-point numbers are the same on both networks (the gateway forwards them unchanged); the
table of [`scope.md`](scope.md) therefore serves the converter as it is. The public sources add
the numbers of four data points the scope knew only by their code, and one it did not list:

| DP | Tuya code | Meaning | Scale |
|---|---|---|---|
| 11 | `work_power` | power | ÷ 10 W (declared; reads 0 when idle, to check while heating) |
| 19 | `temp_correction` | temperature correction | 1 °C, −9…9 |
| 29 | `window_check` | open-window detection | bool |
| 39 | `child_lock` | child lock | bool |
| 103 | `temp_sensitivity` | regulation hysteresis | ÷ 10 °C |

Over Zigbee the mode data point (DP 2) is an **enum index**, not a string. The public converter
observed indices 0, 1, 2, 4 and 5 on its unit and named them itself; those names do not match the
cloud's declared list, so the index ↔ mode table is **not established** and is the first thing M5
measures (set each mode in the vendor app, read the index).

## Property names

Rule: the name Zigbee2MQTT already uses for the nearest device, so that a future upstream
definition and the bridge publish the same thing.

| Property | Type | Change from contract draft 0 |
|---|---|---|
| `local_temperature` | float, °C | none |
| `current_heating_setpoint` | float, °C, 5–40, step 0.5 | none |
| `system_mode` | `heat` \| `off` | none |
| `preset` | `program` \| `manual` \| `eco` \| `holiday` \| `antifrost` | **`schedule` → `program`**, **`frost_protection` → `antifrost`** |
| `running_state` | `heat` \| `idle` | none |
| `window_open` | bool | none (the generic Zigbee2MQTT binary) |
| `window_detection` | `ON` \| `OFF` | none |
| `child_lock` | `LOCK` \| `UNLOCK` | none |
| `local_temperature_calibration` | int, −9…9 | none |
| `holiday_temperature` | float, °C | none |
| `eco_temperature` | float, °C | none |
| `antifrost_temperature` | float, °C | **renamed** from `frost_protection_temperature` |
| `temperature_sensibility` | float, °C | **added** (DP 103) |
| `power` | float, W | none; DP 11 when the channel gives it, else voltage × current |
| `voltage`, `current` | float, V, A | none |
| `energy` | float, kWh, cumulative | none |
| `energy_today`, `energy_yesterday` | float, kWh | **added** (developer API) |
| `fault` | list of fault names (`e1`, `e2`, `e3`), empty when none | none |

Night mode (switch, start, end) has no Zigbee2MQTT equivalent and stays in the `tuya` extension
object.

The Companion reads the draft-0 names (`schedule`, `frost_protection`,
`frost_protection_temperature`) as aliases, so the order in which the bridge and the Companion
are updated does not matter.

## On-site check

Nothing remote can read the fingerprint as the thermostats announce it, and nothing in this
project re-pairs a device unattended. Two ways to close the last doubt, both for the owner to
decide:

1. **Pair one thermostat to the Zigbee coordinator** (it is the first step of M5 anyway): remove
   it from the gateway in the vendor app, put it in pairing mode (per its manual), open pairing in
   Zigbee2MQTT. The interview shows the model id and manufacturer name; the device then appears as
   unsupported until the converter exists. The thermostat leaves the vendor app, its schedule
   stays in the device, and the heater keeps following its pilot wire.
2. **Sniff, without touching anything**: an 802.15.4 capture on the gateway's channel shows the
   Tuya cluster frames; with the gateway's network key unknown, it confirms the radio and nothing
   more. Not worth doing: point 1 of "Evidence" already establishes the radio.
