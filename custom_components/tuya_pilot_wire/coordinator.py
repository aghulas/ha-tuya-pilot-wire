"""MQTT coordinator of the Companion: the bridges' topics merged into one fleet of thermostats.

For each configured prefix it reads `bridge/state`, `bridge/info`, `bridge/devices`, the state
topic of each thermostat and its `availability`. The read side needs no request to the bridge.

It publishes `/set` commands (`async_set_many`) only when `supports_set` allows it, and the
weekly-schedule requests of contract §5: `schedule/get` (`async_get_schedule`) and, only when
`supports_schedule_set` allows it, `schedule/set` (`async_set_schedule_many`). One thermostat
after the other, each answered by the bridge. A command never changes the state held here; the
state changes when the bridge publishes what the device confirmed.

Reading rules, all on the side of "an entity never lies":

- a thermostat's state is the **last object** its bridge published; a property absent from it is
  unknown, not kept from an earlier message;
- a thermostat is usable only while its bridge says `online` and its own availability is not
  `offline`;
- a thermostat that leaves `bridge/devices` leaves the fleet;
- a thermostat listed by **two** bridges at once (while it moves from the Tuya gateway to a Zigbee
  coordinator, or back) is shown from one of them only: the bridge that held it keeps it while it
  is usable there, the other takes over when it is not, or when the first stops listing it. The
  second listing is a **shadow**: read, never shown, never written to.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from . import schedule
from .const import (
    DOMAIN,
    MIN_SET_INTERVAL,
    SCHEDULE_GET,
    SCHEDULE_SET,
    SCHEDULE_TIMEOUT,
    SET_BOUNDS,
    SET_KEYS,
    SET_PRESETS,
    SET_TIMEOUT,
)
from .model import (
    PRESET_MANUAL,
    Thermostat,
    descriptor_identity,
    is_thermostat,
    normalise_state,
    thermostat_from_descriptor,
)

# What is kept of `bridge/info`: versions and channel states. The rest (a Zigbee2MQTT `config`
# block, for one) can hold secrets and is of no use here.
INFO_KEYS = (
    "version",
    "commit",
    "contract",
    "contract_version",
    "channels",
    "read_only",
    "writes",
)

# How long after a coordinator stopped its fleet may still be handed to its successor (seconds).
HANDOVER_MAX_AGE = 5.0

KeyResolver = Callable[[str | None, str | None], str | None]


def _decode_json(payload: str | bytes) -> Any:
    """A payload as JSON, or None when it is not JSON."""
    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        return json.loads(text)
    except (ValueError, UnicodeDecodeError):
        return None


def parse_online(payload: str | bytes) -> bool | None:
    """`{"state": "online"}` or the bare word, as a bool; None when it says neither."""
    data = _decode_json(payload)
    if isinstance(data, dict):
        data = data.get("state")
    elif data is None:
        data = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    if isinstance(data, str):
        text = data.strip().lower()
        if text == "online":
            return True
        if text == "offline":
            return False
    return None


class CompanionCoordinator:
    """State of every pilot-wire thermostat published under the configured prefixes."""

    def __init__(
        self,
        hass: HomeAssistant,
        prefixes: list[str] | tuple[str, ...],
        resolve_key: KeyResolver,
    ) -> None:
        self.hass = hass
        self.prefixes: tuple[str, ...] = tuple(dict.fromkeys(prefixes))
        self._resolve_key = resolve_key
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._last_sent: dict[str, float] = {}  # thermostat key -> monotonic time of its last /set
        self.thermostats: dict[str, Thermostat] = {}
        # Same thermostat listed by a second bridge, kept aside (see the module docstring).
        self.shadows: dict[str, Thermostat] = {}
        self.bridge_online: dict[str, bool | None] = dict.fromkeys(self.prefixes)
        self.bridge_info: dict[str, dict[str, Any]] = {}
        self._by_topic: dict[tuple[str, str], str] = {}
        # Retained messages come in no guaranteed order: what arrives for a prefix before its
        # `bridge/devices` waits here, and is applied or dropped when the list arrives.
        self._listed: set[str] = set()
        self._early: dict[tuple[str, str], dict[str, str | bytes]] = {}
        self._listeners: list[Callable[[], None]] = []
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self.stopped_at: float | None = None  # monotonic time of the last `async_stop`

    # -- listeners ---------------------------------------------------------------------------

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call ``listener`` after every change of the fleet. Returns the function to stop."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # -- lifecycle ---------------------------------------------------------------------------

    async def async_start(self) -> None:
        """Subscribe to every prefix."""
        for prefix in self.prefixes:
            self._unsubscribe.append(
                await mqtt.async_subscribe(self.hass, f"{prefix}/#", self._on_message)
            )

    @callback
    def async_stop(self) -> None:
        """Unsubscribe from every prefix."""
        while self._unsubscribe:
            self._unsubscribe.pop()()
        self.stopped_at = time.monotonic()

    def adopt(self, previous: CompanionCoordinator) -> bool:
        """Start from the fleet of the coordinator this one replaces, when it has just stopped.

        A reload unsubscribes and subscribes again within the same second, and Home Assistant's
        MQTT client then keeps its broker subscription: the retained messages are **not** sent
        again. Without this hand-over the fleet would stay empty until each bridge next
        publishes, which Zigbee2MQTT does for `bridge/devices` only when its device list changes.

        Refused when the prefixes differ, or when the previous coordinator stopped more than
        ``HANDOVER_MAX_AGE`` seconds ago: what it knew is then too old to show, and after such a
        gap the subscription is a new one, so the broker does send the retained messages.
        """
        stopped_at = previous.stopped_at
        if (
            previous.prefixes != self.prefixes
            or stopped_at is None
            or time.monotonic() - stopped_at > HANDOVER_MAX_AGE
        ):
            return False
        self.thermostats = previous.thermostats
        self.shadows = previous.shadows
        self.bridge_online = previous.bridge_online
        self.bridge_info = previous.bridge_info
        self._by_topic = previous._by_topic
        self._listed = previous._listed
        self._early = previous._early
        self._last_sent = previous._last_sent
        return True

    # -- reading -----------------------------------------------------------------------------

    def available(self, key: str) -> bool:
        """True while the thermostat is listed, its bridge online and itself not offline."""
        return self._usable(self.thermostats.get(key))

    def _usable(self, thermostat: Thermostat | None) -> bool:
        if thermostat is None:
            return False
        return self.bridge_online.get(thermostat.prefix) is True and thermostat.online is not False

    def get(self, key: str) -> Thermostat | None:
        """The thermostat when it is usable, else None."""
        return self.thermostats.get(key) if self.available(key) else None

    def open_writes(self, prefix: str) -> tuple[frozenset[str], frozenset[str]]:
        """``(keys, friendly names)`` the bridge of ``prefix`` announces open; empty when closed.

        Open means `read_only` is `false` in its `bridge/info`, and then `writes.keys` and
        `writes.devices` say what and for whom (contract version 5). A version-4 bridge names a
        single `writes.device`, read as a list of one.
        """
        info = self.bridge_info.get(prefix, {})
        writes = info.get("writes")
        if info.get("read_only") is not False or not isinstance(writes, dict):
            return frozenset(), frozenset()
        keys = writes.get("keys")
        devices = writes.get("devices")
        if devices is None and isinstance(writes.get("device"), str):
            devices = [writes["device"]]
        if not isinstance(keys, list) or not isinstance(devices, list):
            return frozenset(), frozenset()
        return (
            frozenset(k for k in keys if isinstance(k, str)),
            frozenset(d for d in devices if isinstance(d, str)),
        )

    def supports_set(self, key: str, set_key: str) -> bool:
        """True when the Companion may publish ``set_key`` to this thermostat.

        The Companion must know the key, and the thermostat's bridge must announce it open for
        this thermostat (`open_writes`).
        """
        thermostat = self.thermostats.get(key)
        if thermostat is None or set_key not in SET_KEYS:
            return False
        keys, devices = self.open_writes(thermostat.prefix)
        return set_key in keys and thermostat.friendly_name in devices

    def supports_schedule_get(self, key: str) -> bool:
        """True when the thermostat's bridge says its developer channel is online."""
        thermostat = self.thermostats.get(key)
        if thermostat is None:
            return False
        channels = self.bridge_info.get(thermostat.prefix, {}).get("channels")
        developer = channels.get("developer") if isinstance(channels, dict) else None
        return isinstance(developer, dict) and developer.get("state") == "online"

    def supports_schedule_set(self, key: str) -> bool:
        """True when the Companion may send ``schedule/set`` for this thermostat.

        Its bridge must list ``schedule/set`` in `writes.requests` and the thermostat in
        `writes.devices` (contract version 6). `read_only` is about `/set`, not this request.
        """
        thermostat = self.thermostats.get(key)
        if thermostat is None:
            return False
        writes = self.bridge_info.get(thermostat.prefix, {}).get("writes")
        if not isinstance(writes, dict):
            return False
        requests, devices = writes.get("requests"), writes.get("devices")
        return (
            isinstance(requests, list)
            and SCHEDULE_SET in requests
            and isinstance(devices, list)
            and thermostat.friendly_name in devices
        )

    def name_of(self, key: str) -> str:
        """The bridge name of a thermostat, or its key when no bridge lists it."""
        thermostat = self.thermostats.get(key)
        return thermostat.friendly_name if thermostat is not None else key

    @staticmethod
    def _check_value(set_key: str, value: Any) -> None:
        if set_key == "preset":
            if value not in SET_PRESETS:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="preset_not_writable",
                    translation_placeholders={
                        "preset": str(value),
                        "presets": ", ".join(SET_PRESETS),
                    },
                )
            return
        low, high, step = SET_BOUNDS[set_key]
        steps = (value - low) / step
        if not low <= value <= high or abs(steps - round(steps)) > 1e-6:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="value_out_of_bounds",
                translation_placeholders={"low": str(low), "high": str(high), "step": str(step)},
            )

    def _check(self, keys: list[str], set_key: str, value: Any) -> list[Thermostat]:
        """Every refusal that needs no bridge, for all thermostats at once. Raises, or returns
        the thermostats to write to, in order."""
        if not keys:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_write_route"
            )
        closed = [key for key in keys if not self.supports_set(key, set_key)]
        if closed:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="write_closed",
                translation_placeholders={
                    "key": set_key,
                    "thermostats": ", ".join(self.name_of(key) for key in closed),
                },
            )
        unusable = [key for key in keys if self.get(key) is None]
        if unusable:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="thermostat_unavailable",
                translation_placeholders={
                    "thermostats": ", ".join(self.name_of(key) for key in unusable)
                },
            )
        self._check_value(set_key, value)
        thermostats = [self.thermostats[key] for key in keys]
        if set_key == "current_heating_setpoint":
            # In any other preset the device does not keep a written setpoint (contract §4).
            elsewhere = [t for t in thermostats if t.preset != PRESET_MANUAL]
            if elsewhere:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="not_in_manual",
                    translation_placeholders={
                        "thermostats": ", ".join(
                            f"{t.friendly_name} ({t.preset or 'unknown'})" for t in elsewhere
                        )
                    },
                )
        return thermostats

    async def async_set(self, key: str, set_key: str, value: Any) -> None:
        """WRITE. One ``/set`` key to one thermostat; see `async_set_many`.

        The bridge's refusal or silence is raised as is (`set_refused`, `set_no_answer`).
        """
        (thermostat,) = self._check([key], set_key, value)
        await self._send(thermostat, set_key, value)

    async def async_set_many(self, keys: list[str], set_key: str, value: Any) -> None:
        """WRITE. Publish one ``/set`` key to several thermostats and wait for each answer.

        Refused before anything is published when the bridge does not announce the key open for
        **every** thermostat, when one is not usable, when the value is outside the key's bounds,
        or, for the manual setpoint, when one thermostat is not in `manual`. Then one command per
        thermostat, one after the other (the bridge writes and reads back one device at a time),
        each with its own transaction and up to ``SET_TIMEOUT`` for its answer. A thermostat
        that is refused or not confirmed does not stop the others; the call then fails naming
        every thermostat not confirmed. Never touches the state held here.
        """
        thermostats = self._check(keys, set_key, value)
        if len(thermostats) == 1:
            await self._send(thermostats[0], set_key, value)
            return
        failed: list[str] = []
        confirmed: list[str] = []
        for thermostat in thermostats:
            try:
                await self._send(thermostat, set_key, value)
            except HomeAssistantError as err:
                reason = (err.translation_placeholders or {}).get("error") or "no answer"
                failed.append(f"{thermostat.friendly_name} ({reason})")
            else:
                confirmed.append(thermostat.friendly_name)
        if failed:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_not_confirmed",
                translation_placeholders={
                    "failed": "; ".join(failed),
                    "confirmed": ", ".join(confirmed) or "none",
                },
            )

    # -- weekly schedule --------------------------------------------------------------------

    async def async_get_schedule(self, key: str) -> dict[str, list[dict[str, Any]]]:
        """Ask the bridge to read the schedule of one thermostat now. Raises unless it answers."""
        thermostat = self.thermostats.get(key)
        if thermostat is None or not self.supports_schedule_get(key):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="schedule_unavailable",
                translation_placeholders={"thermostats": self.name_of(key)},
            )
        response = await self._request(
            thermostat, SCHEDULE_GET, {"device": thermostat.friendly_name}
        )
        data = response.get("data")
        week = schedule.read(data.get("schedule") if isinstance(data, dict) else None)
        if response.get("status") != "ok" or week is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="schedule_refused",
                translation_placeholders={
                    "error": str(response.get("error") or "no schedule in the answer")
                },
            )
        return week

    async def async_set_schedule_many(
        self, keys: list[str], days: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """WRITE. The given days of the weekly schedule, to several thermostats, one by one.

        Refused before anything is published when a day is not described in full (checked here
        as the bridge would), when the bridge does not open ``schedule/set`` for **every**
        thermostat, or when one is not usable. Then one request per thermostat, one after the
        other, ``MIN_SET_INTERVAL`` apart for the same thermostat, each waiting up to
        ``SCHEDULE_TIMEOUT`` for the answer. A thermostat refused or not confirmed does not stop
        the others; the call then fails naming each. Returns the schedule read back, by bridge
        name.
        """
        try:
            checked = schedule.normalise(days)
        except schedule.ScheduleError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=err.code,
                translation_placeholders=err.placeholders,
            ) from err
        if not keys:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_write_route"
            )
        closed = [key for key in keys if not self.supports_schedule_set(key)]
        if closed:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="schedule_closed",
                translation_placeholders={
                    "thermostats": ", ".join(self.name_of(key) for key in closed)
                },
            )
        unusable = [key for key in keys if self.get(key) is None]
        if unusable:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="thermostat_unavailable",
                translation_placeholders={
                    "thermostats": ", ".join(self.name_of(key) for key in unusable)
                },
            )
        results: dict[str, dict[str, Any]] = {}
        failed: list[str] = []
        for key in keys:
            thermostat = self.thermostats[key]
            await self._space(thermostat)
            try:
                response = await self._request(
                    thermostat,
                    SCHEDULE_SET,
                    {"device": thermostat.friendly_name, "days": checked},
                )
            except HomeAssistantError:
                failed.append(f"{thermostat.friendly_name} (no answer)")
                continue
            data = response.get("data")
            data = data if isinstance(data, dict) else {}
            week = schedule.read(data.get("schedule"))
            confirmed = response.get("status") == "ok" and data.get("confirmed") is True
            # Read back as asked, day by day: what the bridge says it read, checked again here.
            if confirmed and (
                week is None or any(week.get(day) != value for day, value in checked.items())
            ):
                confirmed = False
            results[thermostat.friendly_name] = {"confirmed": confirmed, "schedule": week}
            if not confirmed:
                reason = response.get("error") or "the schedule read back differs"
                failed.append(f"{thermostat.friendly_name} ({reason})")
        if failed:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="schedule_not_confirmed",
                translation_placeholders={
                    "failed": "; ".join(failed),
                    "confirmed": ", ".join(
                        name for name, result in results.items() if result["confirmed"]
                    )
                    or "none",
                },
            )
        return results

    async def _space(self, thermostat: Thermostat) -> None:
        """Wait until ``MIN_SET_INTERVAL`` has passed since the last write to the thermostat."""
        last = self._last_sent.get(thermostat.key)
        if last is not None and (delay := last + MIN_SET_INTERVAL - time.monotonic()) > 0:
            await asyncio.sleep(delay)
        self._last_sent[thermostat.key] = time.monotonic()

    async def _request(
        self, thermostat: Thermostat, action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Publish one ``bridge/request/<action>`` and wait for its answer (any status)."""
        transaction = uuid.uuid4().hex
        answer: asyncio.Future[dict[str, Any]] = self.hass.loop.create_future()
        self._pending[transaction] = answer
        try:
            await mqtt.async_publish(
                self.hass,
                f"{thermostat.prefix}/bridge/request/{action}",
                json.dumps(payload | {"transaction": transaction}),
                qos=1,
                retain=False,
            )
            async with asyncio.timeout(SCHEDULE_TIMEOUT):
                return await answer
        except TimeoutError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="set_no_answer"
            ) from err
        finally:
            self._pending.pop(transaction, None)

    async def _send(self, thermostat: Thermostat, set_key: str, value: Any) -> None:
        """Publish one command and wait for the bridge's answer. Raises unless confirmed.

        Waits first until ``MIN_SET_INTERVAL`` has passed since the last command to the same
        thermostat, the bridge's own limit.
        """
        await self._space(thermostat)
        transaction = uuid.uuid4().hex
        answer: asyncio.Future[dict[str, Any]] = self.hass.loop.create_future()
        self._pending[transaction] = answer
        try:
            await mqtt.async_publish(
                self.hass,
                f"{thermostat.prefix}/{thermostat.friendly_name}/set",
                json.dumps({set_key: value, "transaction": transaction}),
                qos=1,
                retain=False,
            )
            async with asyncio.timeout(SET_TIMEOUT):
                response = await answer
        except TimeoutError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="set_no_answer"
            ) from err
        finally:
            self._pending.pop(transaction, None)
        data = response.get("data")
        results = data.get("results") if isinstance(data, dict) else None
        unconfirmed = isinstance(results, list) and any(
            isinstance(result, dict) and result.get("confirmed") is False for result in results
        )
        if response.get("status") != "ok" or unconfirmed:
            error = response.get("error") or ("not confirmed" if unconfirmed else "no reason given")
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_refused",
                translation_placeholders={"error": str(error)},
            )

    # -- ingestion ---------------------------------------------------------------------------

    @callback
    def _on_message(self, msg: Any) -> None:
        self.process_message(msg.topic, msg.payload)

    @callback
    def process_message(self, topic: str, payload: str | bytes) -> None:
        """Take one MQTT message in."""
        prefix, _, suffix = topic.partition("/")
        if prefix not in self.bridge_online or not suffix:
            return
        if suffix == "bridge/state":
            online = parse_online(payload)
            if online is not None and online is not self.bridge_online[prefix]:
                self.bridge_online[prefix] = online
                for key in list(self.shadows):
                    self._arbitrate(key)
                self._notify()
        elif suffix == "bridge/info":
            info = _decode_json(payload)
            if isinstance(info, dict):
                kept = {k: info[k] for k in INFO_KEYS if k in info}
                if kept != self.bridge_info.get(prefix):
                    # `read_only` decides whether a write control may exist: listeners must know.
                    self.bridge_info[prefix] = kept
                    self._notify()
        elif suffix == "bridge/devices":
            self._ingest_devices(prefix, payload)
        elif suffix in (
            "bridge/response/device/set",
            f"bridge/response/{SCHEDULE_GET}",
            f"bridge/response/{SCHEDULE_SET}",
        ):
            response = _decode_json(payload)
            if isinstance(response, dict):
                answer = self._pending.get(str(response.get("transaction")))
                if answer is not None and not answer.done():
                    answer.set_result(response)
        elif suffix.startswith("bridge/") or suffix.endswith(("/set", "/get")):
            return
        elif suffix.endswith("/availability"):
            self._ingest(prefix, suffix.removesuffix("/availability"), "availability", payload)
        else:
            self._ingest(prefix, suffix, "state", payload)

    def _at(self, prefix: str, name: str) -> Thermostat | None:
        """The thermostat, shown or shadow, whose topics are ``<prefix>/<name>``."""
        key = self._by_topic.get((prefix, name))
        for thermostat in (self.thermostats.get(key or ""), self.shadows.get(key or "")):
            if thermostat is not None and (thermostat.prefix, thermostat.friendly_name) == (
                prefix,
                name,
            ):
                return thermostat
        return None

    def _ingest(self, prefix: str, name: str, kind: str, payload: str | bytes) -> None:
        thermostat = self._at(prefix, name)
        if thermostat is None:
            if prefix not in self._listed:
                self._early.setdefault((prefix, name), {})[kind] = payload
            return
        if self._apply(thermostat, kind, payload):
            self._arbitrate(thermostat.key)
            self._notify()

    def _arbitrate(self, key: str) -> None:
        """Show the shadow instead of the thermostat when only the shadow is usable."""
        shadow = self.shadows.get(key)
        shown = self.thermostats.get(key)
        if shadow is None or shown is None:
            return
        if not self._usable(shown) and self._usable(shadow):
            self.thermostats[key], self.shadows[key] = shadow, shown

    @staticmethod
    def _apply(thermostat: Thermostat, kind: str, payload: str | bytes) -> bool:
        """Apply a state or availability payload. Returns whether anything was read."""
        if kind == "availability":
            online = parse_online(payload)
            if online is None:
                return False
            thermostat.online = online
            return True
        state = _decode_json(payload)
        if not isinstance(state, dict):
            return False
        thermostat.state = normalise_state(state)
        return True

    def _ingest_devices(self, prefix: str, payload: str | bytes) -> None:
        entries = _decode_json(payload)
        if not isinstance(entries, list):
            return
        listed: dict[str, Thermostat] = {}
        for entry in entries:
            if not isinstance(entry, dict) or not is_thermostat(entry):
                continue
            key = self._resolve_key(*descriptor_identity(entry))
            described = thermostat_from_descriptor(entry, prefix, key) if key else None
            if described is None:
                continue
            listed[described.key] = described

        # What this prefix published before and no longer lists leaves the fleet; a shadow of it
        # on another bridge takes its place.
        for key, shadow in list(self.shadows.items()):
            if shadow.prefix == prefix and key not in listed:
                del self.shadows[key]
                self._unmap(shadow)
        for key, thermostat in list(self.thermostats.items()):
            if thermostat.prefix == prefix and key not in listed:
                del self.thermostats[key]
                self._unmap(thermostat)
                if (shadow := self.shadows.pop(key, None)) is not None:
                    self.thermostats[key] = shadow

        for key, described in listed.items():
            current = self.thermostats.get(key)
            if current is not None and current.prefix != prefix:
                # Listed by another bridge too: this listing is the shadow.
                self._place(self.shadows, key, described)
                self._arbitrate(key)
            else:
                self._place(self.thermostats, key, described)

        self._listed.add(prefix)
        for (early_prefix, name), payloads in list(self._early.items()):
            if early_prefix != prefix:
                continue
            del self._early[(early_prefix, name)]
            key = self._by_topic.get((prefix, name))
            if key is not None:
                thermostat = self._at(prefix, name)
                for kind, early_payload in payloads.items():
                    if thermostat is not None:
                        self._apply(thermostat, kind, early_payload)
                self._arbitrate(key)
        self._notify()

    def _unmap(self, thermostat: Thermostat) -> None:
        topic = (thermostat.prefix, thermostat.friendly_name)
        if self._by_topic.get(topic) == thermostat.key:
            del self._by_topic[topic]

    def _place(self, where: dict[str, Thermostat], key: str, described: Thermostat) -> None:
        """Put a listed thermostat in ``where`` (the fleet or the shadows), keeping its state
        when its bridge and name are unchanged."""
        current = where.get(key)
        if current is not None and (current.prefix, current.friendly_name) == (
            described.prefix,
            described.friendly_name,
        ):
            current.vendor = described.vendor
            current.model = described.model
            current.ieee_address = described.ieee_address
            return
        if current is not None:
            # Renamed, or moved from another bridge: its topics changed, so what was read on
            # the old ones no longer stands.
            self._unmap(current)
        where[key] = described
        self._by_topic[(described.prefix, described.friendly_name)] = key
