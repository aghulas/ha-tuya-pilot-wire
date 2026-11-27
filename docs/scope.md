# Scope

Status: **scoping** (2026-11-27). Nothing here drives a heater yet.

## Goal

Drive Tuya **pilot-wire thermostats** for electric radiators from Home Assistant through one
integration, whichever network carries them:

- thermostats that stay behind a **Tuya gateway** are published by a bridge,
  [`tuyapilot2mqtt`](https://github.com/aghulas/tuyapilot2mqtt);
- thermostats paired to a **Zigbee coordinator** are published by Zigbee2MQTT;
- both bridges publish to the local Mosquitto broker in the **same Zigbee2MQTT dialect**, and the
  integration in this repository (the **Companion**, domain `tuya_pilot_wire`) talks to the broker
  only.

Moving a thermostat from the Tuya gateway to Zigbee2MQTT must require no rework of entities,
dashboards or automations.

This is the architecture of [`ha-danfoss-ally`](https://github.com/aghulas/ha-danfoss-ally) v2
(bridges + Companion), applied to electric heating.

## Three repositories

| Repository | Role | Mirrors |
|---|---|---|
| [`ha-tuya-pilot-wire`](https://github.com/aghulas/ha-tuya-pilot-wire) (this one) | Home Assistant integration (Companion): rooms, thermostats, schedules, energy. Holds the scope, architecture and roadmap | `ha-danfoss-ally` |
| [`tuyapilot2mqtt`](https://github.com/aghulas/tuyapilot2mqtt) | Bridge daemon and Home Assistant add-on: Tuya gateway → MQTT. Holds the MQTT contract | `danfoss2mqtt` |
| [`pytuya-pilot-wire`](https://github.com/aghulas/pytuya-pilot-wire) | Pure-Python library: data points, codecs, Tuya channels, guarded writes. No Home Assistant dependency | `pydanfoss-cloud` |

## Hardware in scope

| Item | Detail |
|---|---|
| Thermostat | Tuya "FP Thermostat", pilot-wire output, category `wk`, product id `fu1bfwza`; a sub-device of a Tuya gateway |
| Gateway | Tuya multi-protocol gateway (GW002 family) |
| Reference install | six thermostats in three rooms (two per room), one gateway |

Only this product is in scope until a second one is verified on real hardware. The radio between
thermostat and gateway is **not established** (Zigbee is assumed, not verified): it is the first
thing to settle, because the whole Zigbee2MQTT side depends on it (milestone M0).

Out of scope for now: pilot-wire **modules without a thermostat** (they take a mode order —
comfort, eco, frost protection, off — and no setpoint), other Tuya heaters, and pairing (it needs
a physical action on site).

## What is already known

Established on real hardware with a private discovery tool, on the reference install, between
2026-10-31 and 2026-11-15. Restated here without any site data.

### Three channels to a thermostat behind a Tuya gateway

| Channel | Transport | Reads | Writes | Limits |
|---|---|---|---|---|
| **Device-sharing API** | Smart Life account, QR-code login, the SDK Home Assistant's own `tuya` integration uses | on/off, mode, room temperature, setpoint, window state, fault, power, holiday setpoint, temperature correction, window detection, child lock | **Proven**: on/off, mode, setpoint (applied and reported back in under 20 s). Declared but not tried: holiday setpoint, temperature correction, window detection, child lock | No energy counter, no weekly schedule. `update_time` is the last edit of the device record, not the last report |
| **LAN** | Tuya local protocol 3.3 through the gateway, with the gateway's local key | Every data point by number: the above plus voltage, current, cumulative energy, load state, frost and eco setpoints, night mode | **Not tried** | The gateway does not return every data point on each read; voltage and current exist only while heating. The local key has to be obtained once (today: through a Tuya developer project) |
| **Developer API** | Tuya IoT platform project, device shadow properties | Weekly schedule; eco / frost / holiday / manual setpoints; night mode; energy of the day, the day before and total | **Proven** on one thermostat: weekly schedule, written read-modify-write and restored | Needs an active IoT Core subscription on the user's developer project |

### Data points

| DP | Tuya code | Meaning | Scale |
|---|---|---|---|
| 1 | `switch` | on / off | — |
| 2 | `mode` | `eco`, `holiday`, `program`, `manual` | — |
| 16 | `temp_current` | room temperature | ÷ 10 °C |
| 17 | `window_state` | `close` / `open` | — |
| 20 | `fault` | fault bitmap | — |
| 24 | `holiday_temp_set` | holiday setpoint | ÷ 10 °C |
| 50 | `temp_set` | setpoint of the `manual` mode | ÷ 10 °C, 5–40, step 0.5 |
| 101 | `cur_voltage` | voltage, only while heating | ÷ 10 V |
| 102 | `cur_current` | current, only while heating | mA |
| 107 | `energy_all` | cumulative energy | ÷ 10 kWh |
| 116 / 117 | — | frost / eco setpoint | ÷ 10 °C |
| 120–122 | — | night mode: switch, start, end | minutes |
| 124 | `work_state` | load state (`opened` = heating) | — |
| 125–152 | `week_program_18_<day>_<part>` | weekly schedule | see below |

Weekly schedule: 28 data points, 7 days × 4 six-hour parts. Each is base64 of 36 bytes: a 12-byte
header and 24 setpoints at a 15-minute step, °C = byte ÷ 2. The header is one byte repeated,
`0x11` on Monday, Wednesday, Friday and Sunday, `0x55` on the other days; a write keeps the header
it read. Implemented and tested in `pytuya-pilot-wire`.

### Traps

- The thermostats can report a frost-protection mode value that is **absent from the declared
  mode list**; Home Assistant's own integration shows it as unknown. In that mode a setpoint write
  is stored and **not applied**: it takes effect when the mode becomes `manual`.
- In `program` mode the target setpoint is in **no data point**. It can only be derived from the
  weekly schedule and the clock.
- DP 16 is the room temperature and DP 50 the setpoint. An early local calibration had them the
  other way round and produced false "below setpoint" alerts for two weeks.
- Scales of the daily energy figures (÷ 10 assumed, as for the total) are still to be checked
  against a meter during a heating period.

## Principles (carried over from the Danfoss project)

1. **Proven routes only.** An operation goes to the channel proven for it on real hardware by a
   supervised write read back from an independent source. No fallback to a channel that merely
   accepts the call.
2. **Zero optimistic state.** A state topic changes after the channel confirms, never on send. An
   entity with no proven channel up is unavailable, or absent.
3. **Channel-free Companion.** The integration speaks MQTT only. Tuya sessions, keys and protocols
   live in the bridge.
4. **Safety by validation.** Values are checked against the device's own bounds before sending;
   writes are open only for products verified on real hardware.
5. **No secret and no site data** in the repositories, logs or diagnostics: synthetic data in
   tests, redacted diagnostics.
6. **Conservative with the user's account.** The cloud channels ride the user's own Tuya account:
   slow polling by default, clean re-authentication, "unofficial" framing.

## What the Companion will offer

- One `climate` per **room** (rooms are defined in the Companion; Tuya has no room-level grouping
  for these thermostats), with setpoint fan-out to the member thermostats; a thermostat outside
  any room keeps its own.
- Presets: schedule, manual, eco, holiday, frost protection.
- Weekly schedule per room, 15-minute step.
- Per thermostat: room temperature, heating state, window, fault, child lock, window detection,
  temperature correction.
- Power and energy per thermostat and per room, usable in the Energy dashboard.

## Decisions taken

| Date | Decision |
|---|---|
| 2026-11-27 | Three repositories from the start, public |
| 2026-11-27 | Names: `ha-tuya-pilot-wire` (domain `tuya_pilot_wire`), `tuyapilot2mqtt`, `pytuya-pilot-wire` |
| 2026-11-27 | A project of its own, not an extension of the Danfoss Companion: the devices, the dialect property names and the room model differ. Convergence is an open question |

## Open questions

1. **Radio and Zigbee2MQTT support** (M0). Is the thermostat a Zigbee device, with which
   manufacturer name and model id, and does Zigbee2MQTT have a definition for it? If not, an
   external converter is part of the project. If it is not Zigbee at all, the Zigbee2MQTT side
   serves other products only and the scope is redrawn.
2. **Dialect property names.** The draft contract uses the names Zigbee2MQTT gives Tuya
   thermostats (`current_heating_setpoint`, `preset`…). They are fixed on the real Zigbee2MQTT
   definition once M0 has it.
3. **Which channel for the bridge's routine reads.** The sharing API pushes updates over its own
   MQTT link; coverage (which data points, how often) is not measured. The LAN read gives more but
   incompletely.
4. **Schedule without a developer subscription.** The weekly schedule is reachable only through
   the developer API today. Is there a LAN route (the gateway does not return those data points on
   a read; a write was never tried)?
5. **Local key without a developer project.** Same dependency, for the LAN channel.
6. **Target setpoint in `program` mode.** Publish a value derived from the schedule, marked as
   derived, or publish nothing?
7. **One Companion for all heat emitters?** The Danfoss dialect uses the Zigbee thermostat cluster
   names, this one the Tuya names. Whether a shared room / schedule layer is worth extracting is
   decided after both run in production.
