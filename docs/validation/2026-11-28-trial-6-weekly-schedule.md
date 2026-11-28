# Trial 6 — weekly schedule through the bridge's developer channel (2026-11-28)

Status: **run, passed**. Read on the six thermostats, then one day written on one thermostat
and restored. The owner agreed to the exact operation before anything was sent, and checked the
written day in the vendor app.

## Channel

The schedule data points (`week_program_18_<day>_<part>`) are returned only by the Tuya
**developer API** (device shadow properties): the LAN gateway does not return them, and the
sharing API does not declare them. The developer API signs in with the developer project's
access id and secret, **not as a Smart Life client**. It was checked twice that it does not touch
the account's session the bridge holds through the sharing API:

- in the morning, a read of the six schedules by the owner's own developer-API client, while the
  bridge's sharing channel stayed `online`;
- after the owner entered the project's credentials in the add-on's options and `developer` was
  added to `channels`: the bridge restarted with its three channels `online` together, and they
  stayed so through the trial.

A LAN write of these data points was **not** tried and is not proposed: the gateway does not
return them, so nothing local could read a LAN write back. It is worth a trial of its own only if
the developer subscription ends (scope, question 4).

## Setup

- Bridge `tuyapilot2mqtt` 0.5.1 (contract 7; the schedule requests are those of contract 6),
  library `pytuya-pilot-wire` 0.5.1. Channels sharing, LAN and developer `online`.
  `bridge/info.writes.requests`: `["schedule/set"]`, `writes.devices` the six thermostats.
- Companion 0.5.0 loaded (it carries the 0.4.0 schedule read and services). It was **not** the
  path written: the request was published to `<prefix>/bridge/request/schedule/set` by Home
  Assistant's `mqtt.publish` service, with a `transaction`, so that one day of one thermostat was
  written and nothing else.
- Readers: (a) the bridge's log and its state topic (`tuya.schedule`, `tuya.read.schedule.at`);
  (b) the owner's developer-API client on another machine (same API, another client and
  session); (c) the owner, in the vendor app.

## Read (six thermostats)

The bridge read the six schedules with the settings in one request per thermostat and published
them in the state. They matched reader (b), read the same morning, day by day:

| Thermostats | Monday, Tuesday, Thursday, Friday | Wednesday, Saturday, Sunday |
|---|---|---|
| the two of room A | 00:00 5 °C, 01:00 9, 03:00 12, 05:00 15, 07:00 17, 09:00 19, 11:00 21, 16:30 5 | 5 °C all day |
| the four of rooms B and C | 5 °C all day | 5 °C all day |

In the Companion, room A's `climate` showed this schedule as the members' common one, with
`schedule_differing_days` empty.

## Write and restore (one thermostat of room C, Sunday)

Sunday was chosen because it is not occupied, and the slot added (14:00–15:00) was due the next
day: it was restored long before it could run.

| Step | Request `days` | Sent (UTC) | Parts sent | Confirmed | Reader (b) | Owner |
|---|---|---|---|---|---|---|
| 1 write | `sunday`: 00:00 5 °C, 14:00 7 °C, 15:00 5 °C | 12:46:37.37 | 1 (`week_program_18_7_3`) | 12:46:47.91 (10.5 s) | Sunday as written, other days unchanged | ✓ in the app |
| 2 restore | `sunday`: 00:00 5 °C | 12:52:34.54 | 1 (`week_program_18_7_3`) | 12:52:39.76 (5.2 s) | 5 °C all day, other days unchanged | |

- Each request was sent **once** and answered `confirmed` by the bridge after its read-back
  through the developer API. The state topic carried the new Sunday, with
  `tuya.read.schedule.at` at the read-back time.
- Read-modify-write held: only the part holding 12:00–18:00 changed, so only it was sent; the
  three other Sunday parts and the other six days were left untouched, and every part kept the
  12-byte header read from the device.
- The response topic was not captured (the listener timed out); the bridge's log lines are its
  answer.
- Between the two steps the add-on was restarted once by another change of its options; the
  developer channel came back `online` and the restore went through.

## What the trial showed

- The developer channel and the sharing session coexist: the schedule can be read and written
  without any other Smart Life client.
- A schedule write is confirmed in 5 to 11 s through the shadow, within the bridge's 30 s.
- `schedule/set` is proven through the bridge, on one thermostat; the Companion's
  `set_schedule` builds the same request (synthetic tests) and was not the path of this trial.
