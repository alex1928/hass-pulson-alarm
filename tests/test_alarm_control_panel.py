"""Tests for the partition alarm control panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.alarm_control_panel import AlarmControlPanelState
import pytest

from custom_components.pulson_alarm.client import PulsonClient
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
