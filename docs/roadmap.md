# Roadmap

Each milestone ends on something checked on real hardware, and each write is opened by its own
supervised trial ([`architecture.md`](architecture.md), "Rule for adding a route").

| | Milestone | Repository | Done when |
|---|---|---|---|
| **M0** ✅ | **Identify the device.** Radio between thermostat and gateway; Zigbee manufacturer name and model id; whether Zigbee2MQTT defines it and under which property names | `ha-tuya-pilot-wire` (`docs/device.md`) | The fingerprint is written down, and the contract's property names are fixed on the real Zigbee2MQTT definition or on a decision to write a converter |
| **M1** | **Library.** Data-point table, decoding, schedule codec (seeded), dialect codec, the three channel clients, router and write gate | `pytuya-pilot-wire` | Synthetic tests green; a read of the reference install through each channel matches the vendor app |
| **M2** | **Bridge, read only.** Daemon publishing `bridge/state`, `bridge/devices`, state and availability; add-on packaging | `tuyapilot2mqtt` | The reference install's thermostats are on the broker for a week next to the existing setup, with no gap and no account lock |
| **M3** | **Companion, read only.** Config flow, device model, rooms, `climate` per room, sensors, power and energy | `ha-tuya-pilot-wire` | Entities match the vendor app; energy matches the previous local reading over a week |
| **M4** | **Writes**, one at a time: setpoint, mode, on/off; then child lock, window detection, temperature correction, holiday setpoint; then the weekly schedule through `bridge/request` | all three | Each write has its trial record; a room setpoint reaches every member and is read back |
| **M5** | **Zigbee2MQTT path.** One thermostat re-paired to a Zigbee coordinator (with a converter if M0 says so); parity table between the two bridges | `ha-tuya-pilot-wire`, upstream converter if needed | The re-paired thermostat keeps its entities, room and schedule in the Companion |
| **M6** | **Cutover and publication.** The reference install runs on the Companion alone; HACS, add-on repository, PyPI | all three | Previous local bridge and stock integration retired on the reference install; first tagged releases |

## Progress

- **M0** — done 2026-11-27: [`device.md`](device.md). Zigbee, `TS0601` / `_TZE204_fu1bfwza`, not
  defined in Zigbee2MQTT; property names fixed on the nearest upstream definition.
- **M3** — built 2026-11-27 against synthetic messages ([`companion.md`](companion.md)); its "done
  when" (entities match the vendor app, energy matches over a week) is checked on the reference
  install once the bridge (M2) publishes.

## Order of work

M0 comes first and is short: it can change the contract and the scope. M1 and M2 do not wait for
its answer on the gateway side. M5 can be brought forward if M0 shows the device is already
defined in Zigbee2MQTT.

## Not planned

- Pairing or resetting devices from Home Assistant.
- Pilot-wire modules without a thermostat, before a first one is on a test bench.
- Any write that has no independent read-back.
