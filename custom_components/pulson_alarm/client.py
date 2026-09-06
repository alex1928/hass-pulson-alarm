"""MQTT client for the PulsON Alarm cloud.

Protocol notes (reverse-engineered, see docs/):
  * broker speaks MQTT 3.1 (MQIsdp) - NOT 3.1.1 or 5
  * credentials are derived from system id + user PIN
  * the panel publishes a per-element value ONLY after that exact leaf topic is
    subscribed; a '#' wildcard yields just the retained index lists
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from collections.abc import Callable

import aiomqtt
from paho.mqtt.client import MQTTv31

from .const import (
    DEFAULT_PORT,
    FIELDS,
    KEEPALIVE,
    MODULES,
    mqtt_password,
    mqtt_username,
    topic_command,
    topic_index,
    topic_leaf,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_MIN = 5
RECONNECT_MAX = 300


class PulsonState:
    """In-memory mirror of everything the panel reports."""

    def __init__(self) -> None:
        self.partitions: dict[str, dict[str, str]] = {}
        self.inputs: dict[str, dict[str, str]] = {}
        self.outputs: dict[str, dict[str, str]] = {}
        self.online: dict[str, str] = {}
        self.programming: bool | None = None
        self.permissions: str | None = None

    def bucket(self, module: str) -> dict[str, dict[str, str]] | None:
        return {
            "partitions": self.partitions,
            "inputs": self.inputs,
            "outputs": self.outputs,
        }.get(module)


class PulsonClient:
    """Persistent connection to the PulsON cloud broker."""

    def __init__(
        self,
        host: str,
        system_id: str,
        pin: str,
        port: int = DEFAULT_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self.system_id = system_id
        self._pin = pin
        self.username = mqtt_username(system_id, pin)
        self._password = mqtt_password(system_id, pin)

        self.state = PulsonState()
        self.connected = False
        self._client: aiomqtt.Client | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._granular_done: set[str] = set()
        self._listeners: list[Callable[[], None]] = []

    # -- listeners ---------------------------------------------------------
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001 - a bad listener must not kill the loop
                _LOGGER.exception("PulsON listener failed")

    # -- lifecycle ---------------------------------------------------------
    async def async_start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._runner())

    async def async_stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def async_test_connection(self) -> None:
        """Raise if credentials/host are wrong. Used by the config flow."""
        async with self._make_client():
            return

    def _make_client(self) -> aiomqtt.Client:
        ctx = ssl.create_default_context()
        return aiomqtt.Client(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self._password,
            # MQTT 3.1 caps the client id at 23 chars.
            identifier=f"ha-pulson-{int(time.time()) % 100000}",
            protocol=MQTTv31,
            keepalive=KEEPALIVE,
            clean_session=True,
            tls_context=ctx,
        )

    async def _runner(self) -> None:
        delay = RECONNECT_MIN
        while not self._stop.is_set():
            try:
                async with self._make_client() as client:
                    self._client = client
                    self.connected = True
                    self._granular_done.clear()
                    delay = RECONNECT_MIN
                    _LOGGER.info("Connected to PulsON cloud %s", self.host)
                    await self._subscribe_roots(client)
                    self._notify()
                    async for message in client.messages:
                        self._handle(str(message.topic), _decode(message.payload))
                        await self._maybe_subscribe_granular(client)
                        self._notify()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep reconnecting
                _LOGGER.warning("PulsON connection lost (%s); retry in %ss", err, delay)
            finally:
                self.connected = False
                self._client = None
                self._notify()
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, RECONNECT_MAX)

    async def _subscribe_roots(self, client: aiomqtt.Client) -> None:
        for topic in (
            f"system/{self.system_id}/users/{self.username}/#",
            f"system/{self.system_id}/online/#",
            f"system/{self.system_id}/programming",
        ):
            await client.subscribe(topic, qos=0)

    async def _maybe_subscribe_granular(self, client: aiomqtt.Client) -> None:
        """Subscribe exact leaf topics once the index lists are known."""
        for module in MODULES:
            if module in self._granular_done:
                continue
            bucket = self.state.bucket(module)
            if not bucket:
                continue
            self._granular_done.add(module)
            for element_id in list(bucket):
                for field in FIELDS[module]:
                    await client.subscribe(
                        topic_leaf(self.system_id, module, element_id, field), qos=0
                    )
            _LOGGER.debug("Subscribed granular topics for %s: %s", module, list(bucket))

    # -- inbound -----------------------------------------------------------
    def _handle(self, topic: str, payload: str) -> None:
        parts = topic.split("/")
        try:
            seg = parts[parts.index("users") + 2 :]
        except ValueError:
            seg = parts[2:]
        if not seg:
            return
        module = seg[0]

        if module == "online" and len(seg) == 2:
            self.state.online[seg[1]] = payload
            return
        if module == "programming":
            self.state.programming = "1" in payload.split(":")[0]
            return
        if len(seg) == 1:
            if module == "permissions":
                self.state.permissions = payload
                return
            bucket = self.state.bucket(module)
            if bucket is not None:
                for raw_id in payload.split(","):
                    element_id = raw_id.strip()
                    if element_id:
                        bucket.setdefault(element_id, {})
            return
        if len(seg) >= 3:
            bucket = self.state.bucket(module)
            if bucket is not None:
                bucket.setdefault(seg[1], {})[seg[2]] = payload

    # -- outbound ----------------------------------------------------------
    async def async_command(self, subtopic: str, value: str) -> None:
        """Publish a command: topic system/{sid}/{subtopic}, payload {PIN}/{value}."""
        if self._client is None:
            raise RuntimeError("PulsON client is not connected")
        await self._client.publish(
            topic_command(self.system_id, subtopic),
            payload=f"{self._pin}/{value}".encode(),
            qos=0,
            retain=False,
        )

    async def async_element_command(
        self, template: tuple[str, str], element_id: str
    ) -> None:
        subtopic, value = template
        await self.async_command(subtopic.format(id=element_id), value)

    # -- helpers -----------------------------------------------------------
    def index_topics(self) -> list[str]:
        return [topic_index(self.system_id, self.username, m) for m in MODULES]


def _decode(payload: bytes | bytearray | None) -> str:
    if payload is None:
        return ""
    try:
        return bytes(payload).decode()
    except UnicodeDecodeError:
        return bytes(payload).hex()
