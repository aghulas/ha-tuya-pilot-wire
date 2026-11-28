# Architecture

Status: target architecture. Built so far: the Companion's read side ([`companion.md`](companion.md)).
Scope and known facts: [`scope.md`](scope.md); the device: [`device.md`](device.md).
MQTT contract: [`tuyapilot2mqtt/docs/mqtt-contract.md`](https://github.com/aghulas/tuyapilot2mqtt/blob/main/docs/mqtt-contract.md).

```
 [Thermostats on a Zigbee coordinator]        [Thermostats behind a Tuya gateway]
                │                                            │
                │                          sharing API ──────┤
                │                          LAN (3.3) ────────┤   pytuya-pilot-wire
                │                          developer API ────┤   (channels, codecs, write gate)
                ▼                                            ▼
         ┌──────────────┐                            ┌────────────────┐
         │ zigbee2mqtt  │                            │ tuyapilot2mqtt │
         └──────┬───────┘                            └───────┬────────┘
                │  zigbee2mqtt/bridge/devices                │  tuyapilot2mqtt/bridge/devices
                │  zigbee2mqtt/<name> (+ /set)               │  tuyapilot2mqtt/<name> (+ /set)
                │                                            │  tuyapilot2mqtt/bridge/request/…
                └──────────────────────┐   ┌─────────────────┘
                                       ▼   ▼
                               ╔═══════════════════╗
                               ║     Mosquitto     ║
                               ╚═════════╦═════════╝
                                         ▼
                      ┌──────────────────────────────────────┐
                      │  Tuya Pilot Wire Companion (HA)      │
                      │  • subscribes to the bridge prefixes │
                      │  • one device model for both bridges │
                      │  • rooms, setpoint fan-out           │
                      │  • weekly schedules                  │
                      │  • power and energy                  │
                      └──────────────────────────────────────┘
```

## Components

### `pytuya-pilot-wire` (library)

Everything that knows Tuya, with no Home Assistant import:

- the data-point table of each supported product and its decoding;
- the weekly-schedule codec;
- one client per channel (sharing API, LAN, developer API);
- the **router**: for each operation, the channel proven for it, or a refusal;
- the **write gate**: value validation against the device's bounds, verified products only,
  confirmation read after each write;
- the codec between the device model and the Zigbee2MQTT dialect.

### `tuyapilot2mqtt` (bridge and add-on)

A daemon around the library: it holds the Tuya sessions and keys, polls and listens, publishes the
contract's topics, and executes `/set` and `bridge/request/*` through the router. It publishes a
state only once the channel has confirmed it. Packaged as a Home Assistant add-on and as a plain
container.

### Companion (this repository)

Speaks MQTT only. It reads `bridge/devices` and the state topics of every configured prefix,
builds one device model, and owns what Tuya does not have: **rooms**. A room groups thermostats,
shows one `climate`, and fans a setpoint, preset or schedule out to its members. The Companion
never holds a Tuya credential.

## Routing (to be filled by supervised trials)

A cell says which channel is **proven** for the operation. Empty means no route: the bridge
refuses the command and the Companion shows no entity for it.

| Operation | Tuya gateway (`tuyapilot2mqtt`) | Zigbee2MQTT |
|---|---|---|
| Read state | sharing API (proven); LAN for power and energy (proven) | to establish (M5: needs a converter, [`device.md`](device.md)) |
| On / off | sharing API (proven) | |
| Mode | sharing API (proven); `manual` / `program` through the bridge, proven on two thermostats ([trial 2](validation/2026-11-28-trial-2-preset-and-setpoint.md)) | |
| Manual setpoint | sharing API (proven; not applied in frost-protection mode); through the bridge, in `manual` only, proven on two thermostats ([trial 2](validation/2026-11-28-trial-2-preset-and-setpoint.md)) | |
| Holiday setpoint, temperature correction, window detection, child lock | declared by the sharing API, not tried | |
| Eco / frost setpoints, night mode | read by LAN and developer API; no write tried | |
| Weekly schedule | developer API (proven on one thermostat) | |

### Rule for adding a route

One operation at a time, on one designated thermostat, with the owner's agreement: write, then
read back from a source that does not depend on the channel written (another channel, or the
thermostat's own display). The operation is first a closed candidate in the library, then proven
in a change of its own that records the trial.

## Rooms

Tuya exposes no grouping that the thermostats obey, and each thermostat holds its own schedule. So
rooms exist in the Companion only (Home Assistant storage):

- room temperature: mean of the members' temperatures;
- room setpoint, preset and schedule: fanned out to each member, each confirmed separately; a room
  whose members disagree says so instead of showing one of the values;
- room power and energy: sums of the members'.

Whether this logic later moves to a standalone coordinator (as `danfoss-room-coordinator` did for
Danfoss heads on Zigbee2MQTT) is left open until the Companion has run a season.
