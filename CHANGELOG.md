# Changelog

Every version is a tag and a GitHub release of this repository. Unreleased changes are at the
top.

## Unreleased

- **Further settings, where the bridge opens them** (bridge contract version 7): presets `eco`,
  `holiday` and `antifrost` on the climates (the presets open on every member); per thermostat
  and per room, `switch` child lock and open-window detection, `number` temperature calibration
  and holiday setpoint. Each appears only once the bridge lists it as open for the thermostat
  (for a room: for every member), shows only what the device reported, and writes one confirmed
  command per member. Diagnostics map a trial thermostat's name to its number.

- **Moves between bridges** (milestone M5). A thermostat listed by both bridges at once is shown
  from one only: the bridge that held it while it is usable there, the other listing (a
  *shadow*) taking over when it is not, or when the first stops listing it. Nothing is written
  through the shadow; diagnostics show it.
- A thermostat back on its Tuya gateway with a **new device id** keeps its key, entities and
  room: a known IEEE address wins, the new device id is kept as an alias.
- **Zigbee2MQTT external converter** for `TS0601` / `_TZE204_fu1bfwza`, read only, in
  [`zigbee2mqtt/`](zigbee2mqtt/), with its tests; parity table
  ([`docs/z2m-parity.md`](docs/z2m-parity.md)) and on-site procedure
  ([`docs/z2m-trial-procedure.md`](docs/z2m-trial-procedure.md)). Not run on a device yet.
- Brand icon in `custom_components/tuya_pilot_wire/brand/` (HACS and Home Assistant show it).

## 0.3.1 — 2026-11-27

- Two commands to the same thermostat are at least 10 s apart, the bridge's limit
  (`tuyapilot2mqtt` 0.3.0, contract 5): a preset followed by a setpoint waits instead of being
  refused. Commands to different thermostats are not delayed.

## 0.3.0 — 2026-11-27

- Room and thermostat climates: `set_preset_mode` (`program`, `manual`) and `set_temperature`
  (manual setpoint), offered only where the bridge announces the write open (`bridge/info`:
  `read_only: false`, `writes.keys`, `writes.devices`). A room needs every member open.
- Fan-out: one `/set` per member, one after the other, each confirmed by the bridge within 45 s;
  the call fails naming every thermostat not confirmed.
- Refused before anything is sent: closed route, member not responding, value out of 5–30 °C by
  0.5, preset other than `program` / `manual`, setpoint while a member is not in `manual`.
- The "Write trial" option is removed (entry migrated to 1.2); the manual-setpoint `number`
  exists for every thermostat the bridge opens the setpoint for.

## 0.2.0 — 2026-11-27

- The manual setpoint can be enabled for one designated thermostat, for its supervised trial;
  the control appears only while its bridge publishes `read_only: false`. A write validates the
  value, waits for the bridge's answer and never changes the state shown.

## 0.1.1 — 2026-11-27

- The fleet is carried over a reload of the integration (Home Assistant's MQTT client keeps its
  broker subscription, so retained messages are not sent again).
- The read-only climate uses the `native_` names of Home Assistant 2026.11 where they exist.

## 0.1.0 — 2026-11-27

- First usable release, read only: MQTT coordinator over the configured bridge prefixes, one
  device model for `tuyapilot2mqtt` and Zigbee2MQTT; rooms in Home Assistant storage (options
  flow and services); `climate` per room and per thermostat outside any room; sensors and binary
  sensors; redacted diagnostics; English and French.
