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

M0 done (`docs/device.md`). M3 built: the Companion reads (`docs/companion.md`) — MQTT
coordinator, one device model for both bridges, rooms in Home Assistant storage, `climate`,
`sensor`, `binary_sensor`, diagnostics, options flow, room services. **No write is open**
(`const.OPEN_SET_KEYS` is empty). Next: M4, one write at a time, each with its supervised trial.

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
