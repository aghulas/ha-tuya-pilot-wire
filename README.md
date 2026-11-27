# Tuya Pilot Wire Companion for Home Assistant

Drive **Tuya pilot-wire thermostats** for electric radiators from Home Assistant through one
integration, whether a thermostat sits behind a **Tuya gateway** or on a **Zigbee coordinator**.

```
Tuya gateway ───────► tuyapilot2mqtt ──┐
                                       ├──► Mosquitto ──► Tuya Pilot Wire Companion (this integration)
Zigbee coordinator ─► zigbee2mqtt ─────┘
```

Two bridges publish to the local MQTT broker in the same Zigbee2MQTT dialect; the integration
talks to the broker only. Moving a thermostat from one network to the other should need no rework
of entities, dashboards or automations. It is the architecture of
[`ha-danfoss-ally`](https://github.com/aghulas/ha-danfoss-ally) v2, applied to electric heating.

Unofficial: not affiliated with Tuya.

## Status

**Read only.** The integration reads the thermostats the bridges publish and shows them in Home
Assistant, per thermostat and per room: temperature, setpoint, mode, heating, window, fault,
power and energy. Writes open one at a time, each after a supervised trial on real hardware
([roadmap](docs/roadmap.md), M4). The first, the manual setpoint, is built and closed: it can be
enabled for one designated thermostat, for its trial.

- [`docs/companion.md`](docs/companion.md) — what the integration reads, its entities, rooms;
- [`docs/device.md`](docs/device.md) — the thermostat: Zigbee fingerprint, Zigbee2MQTT support;
- [`docs/scope.md`](docs/scope.md) — goal, hardware in scope, what is known from real hardware,
  principles, open questions;
- [`docs/architecture.md`](docs/architecture.md) — components, routing, rooms;
- [`docs/roadmap.md`](docs/roadmap.md) — milestones M0 to M6;
- the [MQTT contract](https://github.com/aghulas/tuyapilot2mqtt/blob/main/docs/mqtt-contract.md),
  in the bridge's repository.

## Installation

Needs Home Assistant 2025.2 or later with the MQTT integration set up, and a bridge publishing
on the same broker ([`tuyapilot2mqtt`](https://github.com/aghulas/tuyapilot2mqtt)).

1. HACS → Custom repositories → `https://github.com/aghulas/ha-tuya-pilot-wire`, type
   Integration; install "Tuya Pilot Wire Companion"; restart Home Assistant.
2. Settings → Devices & services → Add integration → "Tuya Pilot Wire Companion"; give the bridge
   prefixes.
3. Configure → "Add a room" to group thermostats.

| Repository | Role |
|---|---|
| [`pytuya-pilot-wire`](https://github.com/aghulas/pytuya-pilot-wire) | Tuya channels, codecs and guarded writes (library) |
| [`tuyapilot2mqtt`](https://github.com/aghulas/tuyapilot2mqtt) | bridge and add-on: Tuya gateway → MQTT |
| **`ha-tuya-pilot-wire`** (this one) | Home Assistant integration (Companion), domain `tuya_pilot_wire` |

## Hardware

One product so far: the Tuya "FP Thermostat" (pilot-wire thermostat, category `wk`, product id
`fu1bfwza`, Zigbee `TS0601` / `_TZE204_fu1bfwza`) behind a Tuya gateway. If you own another Tuya
pilot-wire thermostat, an issue with its model and what your gateway is would help.

## What it will offer

Read today, written from M4 on:

- One thermostat per **room**, with the setpoint fanned out to the room's thermostats.
- Presets: schedule, manual, eco, holiday, frost protection.
- Weekly schedule per room, at a 15-minute step.
- Window, fault, child lock, temperature correction per thermostat.
- Power and energy per thermostat and per room, for the Energy dashboard.
- No optimistic state: an entity shows what the device confirmed, and is unavailable otherwise.

## Development

```bash
python3.14 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q
```

## License

MIT — see [`LICENSE`](LICENSE).
