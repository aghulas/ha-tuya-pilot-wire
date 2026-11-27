# M3 — read comparison on the reference install (2026-11-27)

Not a write trial: nothing was sent to a thermostat. This records what the Companion showed next
to the two existing readers of the same thermostats, restated without site data.

## Setup

- Companion v0.1.0, then v0.1.1, installed as a custom repository, reading `tuyapilot2mqtt`
  (bridge 0.1.0 then 0.1.1, LAN channel only, one pass a minute).
- Six thermostats, three rooms of two, created with `tuya_pilot_wire.create_room`.
- Compared with: (a) the previous local reader of the same gateway, published through MQTT
  discovery; (b) Home Assistant's own `tuya` integration (device-sharing API).

## Readings

Four readings over five minutes, six thermostats each, one of them heating two radiators.

| Value | Against (a) local reader | Against (b) `tuya` integration |
|---|---|---|
| Room temperature | identical, 24 / 24 | identical, 24 / 24 |
| Cumulative energy | identical, 23 / 24; one reading 0.1 kWh ahead (the two readers do not poll at the same second) | not exposed by (b) |
| Power | within 1 % on the heating thermostats, equal (0 W) on the idle one that reports it | (b) reports 0 W while heating: not comparable |
| Voltage | within 1 V | not exposed by (b) |
| Mode | identical where the bridge read it (3 thermostats of 6) | identical on the same 3 |
| Heating | identical where the bridge read it (3 of 6) | not exposed by (b) |

Rooms: temperature is the mean of the two members; energy and power are their sums; no room
reported a disagreement.

## What the comparison showed

- **Partial LAN reads.** A pass returns temperature and energy for every thermostat, and mode,
  on / off, load state and power for some only. For those the Companion has no entity (never
  published) or an unavailable one, where reader (a) shows `0 W`, `0.0 V` or "not heating". A
  room with such a member has an unknown `climate` state and no power sum. Correct, and of
  little use: the bridge's sharing channel, which reads mode and on / off for every thermostat,
  is what fills these.
- **Retained messages are not replayed after a reload** (found with v0.1.0, fixed in v0.1.1):
  after a room was created, every entity stayed unavailable until the bridge's next pass, and a
  room service called in that window was refused. With v0.1.1 all entities were available
  twelve seconds after a reload, well before the next pass.
- **Home Assistant 2026.11** warned about the former unit and current-temperature names of the
  `climate` platform with v0.1.0; v0.1.1 logs no warning.

## Left for the roadmap's "done when"

M3 asks that energy match the previous local reading **over a week**: the two counters are the
same data point read by two programs, and matched to the tenth on every reading here; the week
runs from this date.
