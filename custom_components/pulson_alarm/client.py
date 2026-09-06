"""aiomqtt transport for the PulsON cloud.

The broker speaks MQTT 3.1 (MQIsdp) only. The panel publishes a per-element
value ONLY after that exact leaf topic is subscribed; a '#' wildcard yields
just the retained index lists.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from typing import TYPE_CHECKING, Final

import aiomqtt
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.ssl import client_context

from .models import EMPTY_STATE, PulsonState, apply_message, known_ids
from .protocol import (
    FIELDS,
    MODULES,
    mqtt_password,
    mqtt_username,
    topic_command,
    topic_leaf,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

KEEPALIVE: Final = 10
RECONNECT_MIN: Final = 5
RECONNECT_MAX: Final = 300
_AUTH_RETURN_CODES: Final = frozenset({134, 135})


class PulsonAuthError(HomeAssistantError):
    """The broker rejected our credentials.

    Subclasses `HomeAssistantError` so that escaping one of these out of a
    service call is reported to the user as a normal integration failure
    rather than an unexpected crash with a traceback.
    """


class PulsonConnectionError(HomeAssistantError):
    """The broker could not be reached.

    See `PulsonAuthError` for why this derives from `HomeAssistantError`.
    """


def decode_payload(payload: bytes | bytearray | None) -> str:
    """Panel text is latin-1, not UTF-8."""
    if payload is None:
        return ""
    return bytes(payload).decode("latin-1", errors="replace")


def _translate(err: Exception) -> Exception:
    if isinstance(err, aiomqtt.MqttCodeError) and err.rc in _AUTH_RETURN_CODES:
        return PulsonAuthError(str(err))
    return PulsonConnectionError(str(err))


class PulsonClient:
    """Long-lived connection to the vendor cloud broker."""

    def __init__(self, host: str, port: int, system_id: str, pin: str) -> None:
        """Store connection parameters and derive credentials."""
        self._host = host
        self._port = port
        self._system_id = system_id
        self._pin = pin
        self.username = mqtt_username(system_id, pin)
        self._password = mqtt_password(system_id, pin)
        self.state: PulsonState = EMPTY_STATE
        self._client: aiomqtt.Client | None = None
        self._stop = asyncio.Event()
        self._client_id = "ha-pulson"
        self._subscribed: set[str] = set()

    def set_client_id(self, value: str) -> None:
        """Set a stable client id (MQTT 3.1 caps it at 23 bytes)."""
        self._client_id = value[:23]

    def _build(self) -> aiomqtt.Client:
        return aiomqtt.Client(
            hostname=self._host,
            port=self._port,
            username=self.username,
            password=self._password,
            identifier=self._client_id,
            protocol=aiomqtt.ProtocolVersion.V31,
            keepalive=KEEPALIVE,
            clean_session=True,
            tls_context=client_context(),
        )

    async def async_verify(self) -> None:
        """Open one probe connection. Raises on failure."""
        try:
            async with self._build():
                return
        except Exception as err:  # any connection failure is normalised below
            raise _translate(err) from err

    async def async_stop(self) -> None:
        """Ask the run loop to finish."""
        self._stop.set()

    async def async_run(
        self,
        on_state: Callable[[PulsonState], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        """Connect, subscribe and fold messages until stopped."""
        delay: float = RECONNECT_MIN
        while not self._stop.is_set():
            try:
                async with self._build() as client:
                    self._client = client
                    delay = RECONNECT_MIN
                    await self._subscribe_roots(client)
                    # A fresh connection means a fresh broker session (clean
                    # session), so leaf subscriptions from before a reconnect
                    # are gone even though `self.state` still remembers the
                    # element ids. Re-subscribe them explicitly: the retained
                    # index topics won't re-trigger this, since re-applying an
                    # index we already hold is a no-op for the reducer.
                    await self._subscribe_granular(client)
                    # Notify unconditionally, even though nothing in `state`
                    # changed. A transport error made the coordinator record an
                    # update failure, and only a *successful* update clears it.
                    # The reducer will not produce one on its own here: after a
                    # reconnect the panel republishes values we already hold, so
                    # `apply_message` keeps returning the same object and
                    # `_consume` stays silent. Without this call every entity
                    # would stay `unavailable` until a value physically changed
                    # on the panel.
                    on_state(self.state)
                    await self._consume_until_stopped(client, on_state)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # any connection failure is normalised below
                translated = _translate(err)
                on_error(translated)
                if isinstance(translated, PulsonAuthError):
                    return
            finally:
                self._client = None
            if self._stop.is_set():
                return
            wait = delay * random.uniform(0.8, 1.2)  # noqa: S311 - jitter, not crypto
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            delay = min(delay * 2, RECONNECT_MAX)

    async def _consume_until_stopped(
        self, client: aiomqtt.Client, on_state: Callable[[PulsonState], None]
    ) -> None:
        """Run the message loop, but abandon it the instant async_stop() fires.

        `client.messages` is an unbounded async generator: once subscribed it
        may sit there awaiting the next publish forever. A plain `async for`
        would block on that await and never notice `_stop`, so the message
        loop and the stop signal are raced against each other explicitly and
        whichever task is still pending is cancelled.
        """
        consume = asyncio.ensure_future(self._consume(client, on_state))
        stopped = asyncio.ensure_future(self._stop.wait())
        try:
            done, pending = await asyncio.wait(
                {consume, stopped}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if consume in done:
                consume.result()
        finally:
            for task in (consume, stopped):
                if not task.done():
                    task.cancel()

    async def _consume(
        self, client: aiomqtt.Client, on_state: Callable[[PulsonState], None]
    ) -> None:
        async for message in client.messages:
            if self._stop.is_set():
                return
            changed = apply_message(
                self.state, str(message.topic), decode_payload(message.payload)
            )
            if changed is not self.state:
                self.state = changed
                await self._subscribe_granular(client)
                on_state(self.state)

    async def _subscribe_roots(self, client: aiomqtt.Client) -> None:
        self._subscribed.clear()
        for topic in (
            f"system/{self._system_id}/users/{self.username}/#",
            f"system/{self._system_id}/online/#",
            f"system/{self._system_id}/programming",
        ):
            await client.subscribe(topic, qos=0)

    async def _subscribe_granular(self, client: aiomqtt.Client) -> None:
        """Subscribe exact leaf topics; this is what makes the panel publish."""
        for module in MODULES:
            for element_id in known_ids(self.state, module):
                key = f"{module}/{element_id}"
                if key in self._subscribed:
                    continue
                self._subscribed.add(key)
                await client.subscribe(
                    [
                        (topic_leaf(self._system_id, module, element_id, field), 0)
                        for field in FIELDS[module]
                    ]
                )

    async def async_command(self, subtopic: str, value: str) -> None:
        """Publish a command. Payload is f'{pin}/{value}'."""
        client = self._client
        if client is None:
            raise PulsonConnectionError("not connected")
        await client.publish(
            topic_command(self._system_id, subtopic),
            payload=f"{self._pin}/{value}".encode(),
            qos=0,
            retain=False,
        )

    async def async_element_command(
        self, template: tuple[str, str], element_id: str
    ) -> None:
        """Publish a per-element command from a CMD_* template."""
        subtopic, value = template
        await self.async_command(subtopic.format(id=element_id), value)
