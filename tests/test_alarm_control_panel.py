"""Tests for the partition alarm control panel."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest

from custom_components.pulson_alarm import protocol
from custom_components.pulson_alarm.client import PulsonClient, PulsonConnectionError
from custom_components.pulson_alarm.protocol import (
    CMD_ARM_AWAY,
    CMD_ARM_NIGHT,
    CMD_DISARM,
)
from tests.helpers import PIN, SID, build_state, setup_with_state

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def state_with_status(status: str):
    username = PulsonClient("h", 8883, SID, PIN).username
    return build_state(
        username,
        [
            (f"system/{SID}/users/{username}/partitions", "1"),
            (f"system/{SID}/partitions/1/name", "Parter"),
            (f"system/{SID}/partitions/1/status", status),
        ],
    )


def state_without_status():
    """Only the retained index topic has arrived: no per-element status yet."""
    username = PulsonClient("h", 8883, SID, PIN).username
    return build_state(
        username,
        [
            (f"system/{SID}/users/{username}/partitions", "1"),
            (f"system/{SID}/partitions/1/name", "Parter"),
        ],
    )


def get_partition_entity(hass: HomeAssistant):
    """Look up the single partition entity created for this test's state.

    Entity IDs depend on device and entity naming, which is an
    implementation detail, so tests search for them by domain rather than
    hardcoding a computed id.
    """
    entity_ids = hass.states.async_entity_ids("alarm_control_panel")
    assert len(entity_ids) == 1
    return hass.states.get(entity_ids[0])


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("0", AlarmControlPanelState.DISARMED),
        ("1", AlarmControlPanelState.ARMED_AWAY),
        ("2", AlarmControlPanelState.ARMED_NIGHT),
        ("3", AlarmControlPanelState.PENDING),
        ("4", AlarmControlPanelState.ARMING),
        ("5", AlarmControlPanelState.TRIGGERED),
        ("14", AlarmControlPanelState.PENDING),
        ("15", AlarmControlPanelState.ARMING),
        ("17", AlarmControlPanelState.TRIGGERED),
        ("19", AlarmControlPanelState.DISARMED),
    ],
)
async def test_state_mapping(
    hass: HomeAssistant, status: str, expected: AlarmControlPanelState
) -> None:
    await setup_with_state(hass, state_with_status(status))
    entity = get_partition_entity(hass)
    assert entity is not None
    assert entity.state == expected


async def test_every_partition_status_maps_to_a_known_state(
    hass: HomeAssistant,
) -> None:
    """Every code 0-19 must map to a real state; every ALARM_STATES code to TRIGGERED.

    `test_state_mapping` above only exercises 10 of the 20 codes. Codes
    6-13, 16 and 18 - fire, gas, CO, medical, tamper, flood, temperature,
    panic, zone tamper - were never checked, so dropping one of them from
    `protocol.ALARM_STATES` would silently render, say, a fire as `unknown`
    without failing anything.
    """
    for code in range(20):
        entry = await setup_with_state(hass, state_with_status(str(code)))
        entity = get_partition_entity(hass)
        assert entity is not None, f"no entity for status {code}"
        assert entity.state != STATE_UNKNOWN, f"status {code} mapped to unknown"
        if code in protocol.ALARM_STATES:
            assert entity.state == AlarmControlPanelState.TRIGGERED, (
                f"status {code} is in ALARM_STATES but did not map to TRIGGERED"
            )
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()


async def test_attributes_expose_raw_values(hass: HomeAssistant) -> None:
    await setup_with_state(hass, state_with_status("19"))
    entity = get_partition_entity(hass)
    assert entity is not None
    assert entity.attributes["raw_status"] == 19
    assert entity.attributes["alarm_in_memory"] is True


async def test_available_once_status_reported(hass: HomeAssistant) -> None:
    """A partition with a real reported status must be available, not stuck out."""
    await setup_with_state(hass, state_with_status("0"))
    entity = get_partition_entity(hass)
    assert entity is not None
    assert entity.state != STATE_UNAVAILABLE
    assert entity.state == AlarmControlPanelState.DISARMED


async def test_unavailable_before_status_arrives(hass: HomeAssistant) -> None:
    """The index topic alone must not make the entity look 'unknown'.

    Before the per-element status leaf arrives, PartitionData.status is None.
    The entity must report unavailable rather than a stale/empty state.
    """
    await setup_with_state(hass, state_without_status())
    entity = get_partition_entity(hass)
    assert entity is not None
    assert entity.state == STATE_UNAVAILABLE


async def test_alarm_disarm_sends_command(hass: HomeAssistant) -> None:
    """The configured PIN disarms.

    Updated from the pre-review version, which called the service with no
    `code` at all: disarming now requires the PIN behind the keypad that
    `_attr_code_format` renders.
    """
    await setup_with_state(hass, state_with_status("0"))
    entity = get_partition_entity(hass)
    assert entity is not None

    with patch(
        "custom_components.pulson_alarm.client.PulsonClient.async_element_command",
        new=AsyncMock(),
    ) as mock_command:
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_disarm",
            {"entity_id": entity.entity_id, "code": PIN},
            blocking=True,
        )

    mock_command.assert_awaited_once_with(CMD_DISARM, "1")


@pytest.mark.parametrize("code", ["9999", "", "1234 ", "12345"])
async def test_alarm_disarm_rejects_a_wrong_code(
    hass: HomeAssistant, code: str
) -> None:
    """A wrong code must raise and must publish nothing.

    The keypad implies the code is checked; before the fix `async_alarm_disarm`
    ignored it entirely, so any four digits disarmed the system.
    """
    await setup_with_state(hass, state_with_status("1"))
    entity = get_partition_entity(hass)
    assert entity is not None

    with patch(
        "custom_components.pulson_alarm.client.PulsonClient.async_element_command",
        new=AsyncMock(),
    ) as mock_command:
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "alarm_control_panel",
                "alarm_disarm",
                {"entity_id": entity.entity_id, "code": code},
                blocking=True,
            )

        mock_command.assert_not_awaited()


async def test_alarm_disarm_rejects_a_missing_code(hass: HomeAssistant) -> None:
    """Omitting `code` entirely must be refused, not treated as authorised."""
    await setup_with_state(hass, state_with_status("1"))
    entity = get_partition_entity(hass)
    assert entity is not None

    with patch(
        "custom_components.pulson_alarm.client.PulsonClient.async_element_command",
        new=AsyncMock(),
    ) as mock_command:
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "alarm_control_panel",
                "alarm_disarm",
                {"entity_id": entity.entity_id},
                blocking=True,
            )

        mock_command.assert_not_awaited()


async def test_alarm_arm_away_sends_command(hass: HomeAssistant) -> None:
    """Arming stays code-free: no `code` is passed and none may be demanded."""
    await setup_with_state(hass, state_with_status("0"))
    entity = get_partition_entity(hass)
    assert entity is not None

    with patch(
        "custom_components.pulson_alarm.client.PulsonClient.async_element_command",
        new=AsyncMock(),
    ) as mock_command:
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_arm_away",
            {"entity_id": entity.entity_id},
            blocking=True,
        )

    mock_command.assert_awaited_once_with(CMD_ARM_AWAY, "1")


async def test_alarm_arm_night_sends_command(hass: HomeAssistant) -> None:
    """Arming stays code-free: no `code` is passed and none may be demanded."""
    await setup_with_state(hass, state_with_status("0"))
    entity = get_partition_entity(hass)
    assert entity is not None

    with patch(
        "custom_components.pulson_alarm.client.PulsonClient.async_element_command",
        new=AsyncMock(),
    ) as mock_command:
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_arm_night",
            {"entity_id": entity.entity_id},
            blocking=True,
        )

    mock_command.assert_awaited_once_with(CMD_ARM_NIGHT, "1")


async def test_transport_failure_surfaces_as_home_assistant_error(
    hass: HomeAssistant,
) -> None:
    """A dead transport must fail the service call cleanly.

    `async_run` is patched out in these tests, so the client never holds a
    connection and `async_command` raises `PulsonConnectionError`. That has
    to reach Home Assistant as a `HomeAssistantError`, otherwise the service
    call logs an unexpected error with a traceback and aborts the caller.
    """
    await setup_with_state(hass, state_with_status("1"))
    entity = get_partition_entity(hass)
    assert entity is not None

    with pytest.raises(PulsonConnectionError) as caught:
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_disarm",
            {"entity_id": entity.entity_id, "code": PIN},
            blocking=True,
        )

    assert isinstance(caught.value, HomeAssistantError)


def state_two_partitions():
    """Two partitions, each with its own panel-supplied name."""
    username = PulsonClient("h", 8883, SID, PIN).username
    return build_state(
        username,
        [
            (f"system/{SID}/users/{username}/partitions", "1,2"),
            (f"system/{SID}/partitions/1/name", "Parter"),
            (f"system/{SID}/partitions/1/status", "0"),
            (f"system/{SID}/partitions/2/name", "Piętro"),
            (f"system/{SID}/partitions/2/status", "1"),
        ],
    )


async def test_partitions_are_named_individually(hass: HomeAssistant) -> None:
    """Two partitions must not both fall back to the shared device name.

    With `_attr_name = None` every partition entity inherited the device name
    "PulsON Alarm", so a two-partition panel produced two indistinguishable
    entities. The panel-supplied names have to reach the entity.
    """
    await setup_with_state(hass, state_two_partitions())
    entity_ids = hass.states.async_entity_ids("alarm_control_panel")
    assert len(entity_ids) == 2

    names = sorted(
        hass.states.get(entity_id).attributes["friendly_name"]
        for entity_id in entity_ids
    )
    assert names == ["PulsON Alarm Parter", "PulsON Alarm Piętro"]
    assert len(set(entity_ids)) == 2


async def test_partition_name_falls_back_to_the_id(hass: HomeAssistant) -> None:
    """A partition the panel never named still gets a distinguishing name."""
    username = PulsonClient("h", 8883, SID, PIN).username
    state = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/partitions", "7"),
            (f"system/{SID}/partitions/7/status", "0"),
        ],
    )
    await setup_with_state(hass, state)
    entity = get_partition_entity(hass)
    assert entity is not None
    assert entity.attributes["friendly_name"] == "PulsON Alarm Partition 7"


async def test_alarm_flag_triggers_panel_and_sensor_together(
    hass: HomeAssistant,
) -> None:
    """The card and the safety sensor must never contradict each other.

    `alarm` and `status` are independent MQTT leaves. Here `status` is a
    plain ARMED value while `alarm` is set, which before the fix rendered as
    `armed_away` on the panel card and "Detected" on the safety sensor for
    the very same partition.
    """
    username = PulsonClient("h", 8883, SID, PIN).username
    state = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/partitions", "1"),
            (f"system/{SID}/partitions/1/name", "Parter"),
            (f"system/{SID}/partitions/1/status", "1"),
            (f"system/{SID}/partitions/1/alarm", "1"),
        ],
    )
    await setup_with_state(hass, state)

    panel = get_partition_entity(hass)
    assert panel is not None
    assert panel.state == AlarmControlPanelState.TRIGGERED

    sensor_ids = [
        entity_id
        for entity_id in hass.states.async_entity_ids("binary_sensor")
        if entity_id.endswith("parter_alarm")
    ]
    assert len(sensor_ids) == 1
    assert hass.states.get(sensor_ids[0]).state == "on"


class _FakeMessage:
    """Stand-in for aiomqtt.Message."""

    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


class _FakeBroker:
    """aiomqtt stand-in that republishes values the reducer already holds."""

    def __init__(self, client: PulsonClient, messages: list[_FakeMessage]) -> None:
        self._client = client
        self._messages = messages

    async def __aenter__(self) -> _FakeBroker:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def subscribe(self, topic: Any, qos: int = 0) -> None:
        return None

    @property
    def messages(self) -> Any:
        async def gen() -> Any:
            for message in self._messages:
                yield message
            await self._client.async_stop()
            # Never set: blocks until the consumer task is cancelled, same as
            # a real broker with nothing further to say.
            await asyncio.Event().wait()  # pragma: no cover - cancelled by stop

        return gen()


async def test_entities_recover_after_a_reconnect_with_no_changes(
    hass: HomeAssistant,
) -> None:
    """A reconnect must restore availability even if nothing actually changed.

    `_handle_error` sets `last_update_success = False`, and only a successful
    update clears it. After a reconnect the panel republishes values we
    already hold, so `apply_message` returns the same object and the message
    loop stays silent - which used to leave every entity `unavailable`
    forever. This drives the *real* `async_run` connect path against the real
    coordinator, so it fails unless that path notifies unconditionally.
    """
    state = state_with_status("0")
    transport: dict[str, Any] = {}
    entry = await setup_with_state(hass, state, transport)
    coordinator = entry.runtime_data
    client = coordinator.client
    # What the client was holding when the connection dropped.
    client.state = state

    assert get_partition_entity(hass).state == AlarmControlPanelState.DISARMED

    transport["on_error"](PulsonConnectionError("broker went away"))
    await hass.async_block_till_done()
    assert get_partition_entity(hass).state == STATE_UNAVAILABLE

    # Reconnect. The panel republishes exactly the value already folded in,
    # so the reducer produces no change and `_consume` never notifies.
    broker = _FakeBroker(
        client, [_FakeMessage(f"system/{SID}/partitions/1/status", b"0")]
    )
    with patch(
        "custom_components.pulson_alarm.client.aiomqtt.Client", return_value=broker
    ):
        await client.async_run(transport["on_state"], transport["on_error"])
    await hass.async_block_till_done()

    assert client.state is state, "the republished value must be a reducer no-op"
    assert get_partition_entity(hass).state == AlarmControlPanelState.DISARMED
