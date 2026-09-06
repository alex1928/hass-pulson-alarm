"""Tests for the MQTT transport."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import aiomqtt
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.pulson_alarm.client import (
    PulsonAuthError,
    PulsonClient,
    PulsonConnectionError,
    decode_payload,
)
from custom_components.pulson_alarm.protocol import (
    FIELDS,
    MODULE_PARTITIONS,
    topic_leaf,
)


class FakeMessage:
    """Stand-in for aiomqtt.Message."""

    def __init__(self, topic: str, payload: bytes) -> None:
        """Store the topic and payload the fake client will yield."""
        self.topic = topic
        self.payload = payload


def make_client() -> PulsonClient:
    return PulsonClient(host="h", port=8883, system_id="SID", pin="1234")


def test_username_is_derived() -> None:
    client = make_client()
    assert client.username.startswith("SID_")


async def test_command_without_connection_raises() -> None:
    client = make_client()
    with pytest.raises(PulsonConnectionError):
        await client.async_command("panic_alarm", "1")


async def test_transport_errors_are_home_assistant_errors() -> None:
    """Both transport errors must be catchable as `HomeAssistantError`.

    They escape through service calls; a bare `Exception` makes Home
    Assistant log an unexpected error with a traceback and aborts the
    calling automation instead of reporting a normal integration failure.
    """
    client = make_client()
    with pytest.raises(HomeAssistantError):
        await client.async_command("panic_alarm", "1")

    with patch("custom_components.pulson_alarm.client.aiomqtt.Client") as factory:
        factory.return_value.__aenter__.side_effect = aiomqtt.MqttCodeError(134)
        with pytest.raises(HomeAssistantError):
            await make_client().async_verify()

    assert issubclass(PulsonAuthError, HomeAssistantError)
    assert issubclass(PulsonConnectionError, HomeAssistantError)


async def test_command_publishes_pin_prefixed_payload() -> None:
    client = make_client()
    mqtt = AsyncMock()
    client._client = mqtt
    await client.async_command("partitions/1/set_arm", "1")
    mqtt.publish.assert_awaited_once_with(
        "system/SID/partitions/1/set_arm", payload=b"1234/1", qos=0, retain=False
    )


async def test_element_command_formats_id() -> None:
    client = make_client()
    mqtt = AsyncMock()
    client._client = mqtt
    await client.async_element_command(("inputs/{id}/block_set", "1"), "3")
    assert mqtt.publish.await_args.args[0] == "system/SID/inputs/3/block_set"


def test_decode_uses_latin1() -> None:
    assert decode_payload(b"wej\xf6cie") == "wejöcie"
    assert decode_payload(None) == ""


async def test_verify_maps_auth_failure() -> None:
    err = aiomqtt.MqttCodeError(134)
    with patch("custom_components.pulson_alarm.client.aiomqtt.Client") as factory:
        factory.return_value.__aenter__.side_effect = err
        with pytest.raises(PulsonAuthError):
            await make_client().async_verify()


async def test_verify_maps_other_failure() -> None:
    with patch("custom_components.pulson_alarm.client.aiomqtt.Client") as factory:
        factory.return_value.__aenter__.side_effect = OSError("boom")
        with pytest.raises(PulsonConnectionError):
            await make_client().async_verify()


async def test_run_folds_messages_and_subscribes_granular() -> None:
    client = make_client()
    updates: list[Any] = []
    messages = [
        FakeMessage(f"system/SID/users/{client.username}/partitions", b"1"),
        FakeMessage("system/SID/partitions/1/status", b"1"),
    ]

    class FakeMqtt:
        def __init__(self) -> None:
            self.subscribed: list[Any] = []

        async def __aenter__(self) -> FakeMqtt:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def subscribe(self, topic: Any, qos: int = 0) -> None:
            self.subscribed.append(topic)

        @property
        def messages(self) -> Any:
            async def gen() -> Any:
                for message in messages:
                    yield message
                await client.async_stop()
                # Never set: blocks forever until the consumer task is
                # cancelled, same as a real broker with nothing left to say.
                await asyncio.Event().wait()  # pragma: no cover - cancelled by stop

            return gen()

    fake = FakeMqtt()
    with patch(
        "custom_components.pulson_alarm.client.aiomqtt.Client", return_value=fake
    ):
        await client.async_run(updates.append, lambda _err: None)

    assert client.state.partitions["1"].status == 1
    assert any(isinstance(sub, list) for sub in fake.subscribed)
    assert updates


async def test_run_resubscribes_granular_after_reconnect() -> None:
    """A second connection must re-issue the per-element leaf subscriptions.

    `self.state` survives a reconnect but the `_subscribed` bookkeeping is
    cleared by `_subscribe_roots` on every fresh connect (a clean MQTT
    session forgets prior subscriptions). Without the unconditional
    `_subscribe_granular(client)` call in `async_run`, already-known
    elements would never have their leaf topics re-subscribed after a
    reconnect, and the panel would stop publishing their values entirely.
    """
    client = make_client()

    class FakeMqttFirstConnection:
        """Announces partition '1', then simply drops the stream."""

        def __init__(self) -> None:
            self.subscribed: list[Any] = []

        async def __aenter__(self) -> FakeMqttFirstConnection:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def subscribe(self, topic: Any, qos: int = 0) -> None:
            self.subscribed.append(topic)

        @property
        def messages(self) -> Any:
            async def gen() -> Any:
                yield FakeMessage(
                    f"system/SID/users/{client.username}/partitions", b"1"
                )
                # The generator simply ends here (broker closed the
                # stream), which is what sends async_run back around to
                # its reconnect branch.

            return gen()

    class FakeMqttSecondConnection:
        """Delivers no messages; just records subscriptions, then stops."""

        def __init__(self) -> None:
            self.subscribed: list[Any] = []

        async def __aenter__(self) -> FakeMqttSecondConnection:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def subscribe(self, topic: Any, qos: int = 0) -> None:
            self.subscribed.append(topic)
            await client.async_stop()

        @property
        def messages(self) -> Any:
            async def gen() -> Any:
                await asyncio.Event().wait()  # pragma: no cover - cancelled by stop
                yield FakeMessage("unused", b"")  # pragma: no cover - never reached

            return gen()

    first = FakeMqttFirstConnection()
    second = FakeMqttSecondConnection()
    with (
        patch(
            "custom_components.pulson_alarm.client.aiomqtt.Client",
            side_effect=[first, second],
        ),
        # Neutralise the real jittered reconnect backoff so the test does
        # not sit on RECONNECT_MIN seconds of real sleep.
        patch("custom_components.pulson_alarm.client.RECONNECT_MIN", 0.0),
    ):
        await client.async_run(lambda _s: None, lambda _err: None)

    expected_leaf_subscriptions = [
        (topic_leaf("SID", MODULE_PARTITIONS, "1", field), 0)
        for field in FIELDS[MODULE_PARTITIONS]
    ]
    assert expected_leaf_subscriptions in second.subscribed


async def test_run_notifies_on_every_connect_even_without_changes() -> None:
    """Every successful connect must push a state notification.

    After a reconnect the panel republishes the values we already hold, so
    `apply_message` keeps returning the very same object and `_consume`
    never fires `on_state`. The coordinator, however, recorded an update
    failure when the connection dropped and only clears it on a successful
    update - so without an unconditional notification at connect time every
    entity stays `unavailable` until something physically changes on the
    panel.
    """
    client = make_client()
    events: list[str] = []

    class FakeMqttFirstConnection:
        """Announces partition '1' with a status, then drops the stream."""

        async def __aenter__(self) -> FakeMqttFirstConnection:
            events.append("connect-1")
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def subscribe(self, topic: Any, qos: int = 0) -> None:
            return None

        @property
        def messages(self) -> Any:
            async def gen() -> Any:
                yield FakeMessage(
                    f"system/SID/users/{client.username}/partitions", b"1"
                )
                yield FakeMessage("system/SID/partitions/1/status", b"1")
                # Generator ends: the broker closed the stream, which sends
                # async_run around to its reconnect branch.

            return gen()

    class FakeMqttSecondConnection:
        """Republishes the identical status the reducer already holds."""

        async def __aenter__(self) -> FakeMqttSecondConnection:
            events.append("connect-2")
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def subscribe(self, topic: Any, qos: int = 0) -> None:
            return None

        @property
        def messages(self) -> Any:
            async def gen() -> Any:
                yield FakeMessage("system/SID/partitions/1/status", b"1")
                await client.async_stop()
                # Never set: blocks until the consumer task is cancelled.
                await asyncio.Event().wait()  # pragma: no cover - cancelled by stop

            return gen()

    def on_state(_state: Any) -> None:
        events.append("notify")

    with (
        patch(
            "custom_components.pulson_alarm.client.aiomqtt.Client",
            side_effect=[FakeMqttFirstConnection(), FakeMqttSecondConnection()],
        ),
        patch("custom_components.pulson_alarm.client.RECONNECT_MIN", 0.0),
    ):
        await client.async_run(on_state, lambda _err: None)

    # The republished value really was a no-op for the reducer...
    assert client.state.partitions["1"].status == 1
    # ...yet the second connection still notified.
    after_reconnect = events[events.index("connect-2") + 1 :]
    assert "notify" in after_reconnect, events


async def test_run_reports_auth_error_and_stops() -> None:
    client = make_client()
    errors: list[Exception] = []
    with patch("custom_components.pulson_alarm.client.aiomqtt.Client") as factory:
        factory.return_value.__aenter__.side_effect = aiomqtt.MqttCodeError(135)
        await client.async_run(lambda _s: None, errors.append)
    assert isinstance(errors[0], PulsonAuthError)
