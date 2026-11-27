"""MQTT coordinator of the Companion: the bridges' topics merged into one fleet of thermostats.

For each configured prefix it reads `bridge/state`, `bridge/info`, `bridge/devices`, the state
topic of each thermostat and its `availability`. The read side needs no request to the bridge.

It publishes one thing, and only when `supports_set` allows it: a `/set` command (`async_set`).
A command never changes the state held here; the state changes when the bridge publishes what
the device confirmed.

Reading rules, all on the side of "an entity never lies":

- a thermostat's state is the **last object** its bridge published; a property absent from it is
  unknown, not kept from an earlier message;
- a thermostat is usable only while its bridge says `online` and its own availability is not
  `offline`;
- a thermostat that leaves `bridge/devices` leaves the fleet.
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

from .const import DOMAIN, OPEN_SET_KEYS, SET_BOUNDS, SET_TIMEOUT, TRIAL_SET_KEYS
from .model import (
    Thermostat,
    descriptor_identity,
    is_thermostat,
    normalise_state,
    thermostat_from_descriptor,
)

# What is kept of `bridge/info`: versions and channel states. The rest (a Zigbee2MQTT `config`
# block, for one) can hold secrets and is of no use here.
INFO_KEYS = ("version", "commit", "contract", "contract_version", "channels", "read_only")

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
        trial_thermostat: str | None = None,
    ) -> None:
        self.hass = hass
        self.prefixes: tuple[str, ...] = tuple(dict.fromkeys(prefixes))
        self._resolve_key = resolve_key
        self.trial_thermostat = trial_thermostat or None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.thermostats: dict[str, Thermostat] = {}
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
        self.bridge_online = previous.bridge_online
        self.bridge_info = previous.bridge_info
        self._by_topic = previous._by_topic
        self._listed = previous._listed
        self._early = previous._early
        return True

    # -- reading -----------------------------------------------------------------------------

    def available(self, key: str) -> bool:
        """True while the thermostat is listed, its bridge online and itself not offline."""
        thermostat = self.thermostats.get(key)
        if thermostat is None:
            return False
        return self.bridge_online.get(thermostat.prefix) is True and thermostat.online is not False

    def get(self, key: str) -> Thermostat | None:
        """The thermostat when it is usable, else None."""
        return self.thermostats.get(key) if self.available(key) else None

    def supports_set(self, key: str, set_key: str) -> bool:
        """True when the Companion may publish ``set_key`` to this thermostat.

        The key must be open for every thermostat, or under trial and this thermostat the one
        designated for trials; and the thermostat's bridge must have said it is not read only.
        """
        thermostat = self.thermostats.get(key)
        if thermostat is None:
            return False
        allowed = set_key in OPEN_SET_KEYS or (
            set_key in TRIAL_SET_KEYS and key == self.trial_thermostat
        )
        return allowed and self.bridge_info.get(thermostat.prefix, {}).get("read_only") is False

    async def async_set(self, key: str, set_key: str, value: float) -> None:
        """WRITE. Publish one ``/set`` key to one thermostat and wait for the bridge's answer.

        Refused before anything is published when no route is open for this key on this
        thermostat, when the thermostat is not usable, or when the value is outside the key's
        bounds or off its step. Raises when the bridge refuses or does not answer. Never touches
        the state held here: the bridge publishes it once the device confirmed.
        """
        if not self.supports_set(key, set_key):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_write_route"
            )
        thermostat = self.get(key)
        if thermostat is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="thermostat_unavailable"
            )
        low, high, step = SET_BOUNDS[set_key]
        steps = (value - low) / step
        if not low <= value <= high or abs(steps - round(steps)) > 1e-6:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="value_out_of_bounds",
                translation_placeholders={"low": str(low), "high": str(high), "step": str(step)},
            )

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
        if response.get("status") != "ok":
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_refused",
                translation_placeholders={"error": str(response.get("error") or "no reason given")},
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
        elif suffix == "bridge/response/device/set":
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

    def _ingest(self, prefix: str, name: str, kind: str, payload: str | bytes) -> None:
        key = self._by_topic.get((prefix, name))
        if key is None:
            if prefix not in self._listed:
                self._early.setdefault((prefix, name), {})[kind] = payload
            return
        if self._apply(self.thermostats[key], kind, payload):
            self._notify()

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

        # What this prefix published before and no longer lists leaves the fleet.
        for key, thermostat in list(self.thermostats.items()):
            if thermostat.prefix == prefix and key not in listed:
                del self.thermostats[key]
                self._by_topic.pop((prefix, thermostat.friendly_name), None)

        for key, described in listed.items():
            current = self.thermostats.get(key)
            if current is not None and (current.prefix, current.friendly_name) == (
                prefix,
                described.friendly_name,
            ):
                current.vendor = described.vendor
                current.model = described.model
                current.ieee_address = described.ieee_address
                continue
            if current is not None:
                # Renamed, or moved from another bridge: its topics changed, so what was read on
                # the old ones no longer stands.
                self._by_topic.pop((current.prefix, current.friendly_name), None)
            self.thermostats[key] = described
            self._by_topic[(prefix, described.friendly_name)] = key

        self._listed.add(prefix)
        for (early_prefix, name), payloads in list(self._early.items()):
            if early_prefix != prefix:
                continue
            del self._early[(early_prefix, name)]
            key = self._by_topic.get((prefix, name))
            if key is not None:
                for kind, early_payload in payloads.items():
                    self._apply(self.thermostats[key], kind, early_payload)
        self._notify()
