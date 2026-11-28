# ha-tuya-pilot-wire — guide for agent sessions

Home Assistant integration (Companion, domain `tuya_pilot_wire`) of the pilot-wire project, and
the home of its scope. Read `docs/scope.md`, then `docs/architecture.md`, `docs/roadmap.md`, `docs/device.md` and
`docs/companion.md`.

## The three repositories

- `~/dev/ha-tuya-pilot-wire` — this one: integration, scope, architecture, roadmap.
- `~/dev/tuyapilot2mqtt` — bridge and add-on; owns the contract `docs/mqtt-contract.md`.
- `~/dev/pytuya-pilot-wire` — library: everything that knows Tuya.

Model to follow, file by file: `~/dev/ha-danfoss-ally` (v2 Companion: `mqtt_companion.py`,
`companion_rooms.py`, `companion_adapter.py`, `docs/companion-contract.md`), `~/dev/danfoss2mqtt`
and `~/dev/pydanfoss-cloud`. Reuse their patterns; do not import their code.

## Non-negotiable rules

- **Public repositories.** No secret (session token, local key, access id / secret), no real
  device id, no site data — in code, tests, docs, diagnostics, logs or commit messages. A finding
  from a real install is restated generically before it enters a repository. `git grep` before a
  push.
- **Channel-free Companion.** The integration speaks to the MQTT broker only. No Tuya SDK, no
  `tinytuya`, no credential here.
- **Proven routes only, zero optimistic state.** An entity exists for an operation only when a
  bridge has a proven route for it; it shows what the device confirmed and is unavailable
  otherwise. Never an entity that lies.
- **Write safety.** Value validation before sending; writes only for products verified on real
  hardware; one supervised trial per new write, on one designated thermostat, with the owner's
  agreement on the exact operation, read back from an independent source, recorded in
  `docs/validation/`.
- **Never change a deployed `unique_id`.**

## Where the work stands

M0 done (`docs/device.md`). M3 delivered: the Companion reads (`docs/companion.md`) and runs on
the reference install (record in `docs/validation/`). M4: since v0.3.0 the Companion builds two
writes, the preset and the manual setpoint, on room and thermostat climates (fan-out, one
confirmed command per member) and a per-thermostat `number`; since v0.5.0 also the settings of
contract version 7: presets `eco` / `holiday` / `antifrost`, and per thermostat and per room a
`switch` for child lock and window detection and a `number` for calibration and holiday setpoint.
**It opens none by itself** (`SET_KEYS`, `SET_PRESETS` are what it can build): a key reaches a
thermostat only while its bridge announces it in `bridge/info` (`read_only: false`,
`writes.keys`, `writes.presets`, `writes.devices`); `writes.trial` is never offered. The
designation and the supervised trials live on the bridge (`~/dev/tuyapilot2mqtt`); the trial
protocol is `docs/validation/trial-1-manual-setpoint-protocol.md`. Since v0.4.0 the weekly schedule
(contract 6, bridge developer channel): read as climate attributes, `get_schedule` /
`set_schedule` services, `schedule/set` open only while `bridge/info.writes.requests` lists it.

## Quality

```
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q
```

Green before a commit; CI runs the same, plus `hassfest` and the HACS validation. The test
harness follows the Home Assistant line run in production (pin in `requirements-dev.txt`).
The mocked broker of the harness replays no retained message and knows nothing of Home
Assistant's subscription debouncing: what depends on the real broker (retained messages after a
reload, for one) is checked on the reference install, and written down in `docs/companion.md`.

## Commit, push

Messages in English. Commit and push only when the owner asks; one branch per non-trivial change.
