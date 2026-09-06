"""Tests for the partition alarm control panel."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.const import STATE_UNAVAILABLE
import pytest

from custom_components.pulson_alarm.client import PulsonClient
from custom_components.pulson_alarm.protocol import (
    CMD_ARM_AWAY,
    CMD_ARM_NIGHT,
    CMD_DISARM,
)
from tests.helpers import SID, build_state, setup_with_state

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def state_with_status(status: str):
    username = PulsonClient("h", 8883, SID, "1234").username
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
    username = PulsonClient("h", 8883, SID, "1234").username
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
            {"entity_id": entity.entity_id},
            blocking=True,
        )

    mock_command.assert_awaited_once_with(CMD_DISARM, "1")


async def test_alarm_arm_away_sends_command(hass: HomeAssistant) -> None:
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
