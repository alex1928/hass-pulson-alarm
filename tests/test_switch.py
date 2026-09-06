"""Tests for output and bypass switches."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from homeassistant.const import STATE_UNAVAILABLE, EntityCategory
from homeassistant.helpers import entity_registry as er

from custom_components.pulson_alarm.client import PulsonClient
from custom_components.pulson_alarm.protocol import (
    CMD_BLOCK,
    CMD_OUTPUT_OFF,
    CMD_OUTPUT_ON,
    CMD_UNBLOCK,
)
from tests.helpers import SID, build_state, setup_with_state

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def state():
    username = PulsonClient("h", 8883, SID, "1234").username
    return build_state(
        username,
        [
            (f"system/{SID}/users/{username}/outputs", "1"),
            (f"system/{SID}/users/{username}/inputs", "2"),
            (f"system/{SID}/outputs/1/name", "Brama"),
            (f"system/{SID}/outputs/1/status", "0"),
            (f"system/{SID}/inputs/2/name", "Salon"),
            (f"system/{SID}/inputs/2/block", "0"),
            (f"system/{SID}/inputs/2/block_enable", "1"),
        ],
    )


def find(hass: HomeAssistant, needle: str) -> str:
    matches = [e for e in hass.states.async_entity_ids("switch") if needle in e]
    assert matches, (
        f"no switch matching {needle!r} in {hass.states.async_entity_ids('switch')}"
    )
    return matches[0]


async def test_output_off_and_turn_on_publishes(hass: HomeAssistant) -> None:
    await setup_with_state(hass, state())
    entity_id = next(e for e in hass.states.async_entity_ids("switch") if "brama" in e)
    assert hass.states.get(entity_id).state == "off"
    with patch(
        "custom_components.pulson_alarm.client.PulsonClient.async_element_command",
        new=AsyncMock(),
    ) as command:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )
    assert command.await_args.args[0] == CMD_OUTPUT_ON
    assert command.await_args.args[1] == "1"


async def test_output_on_and_turn_off_publishes(hass: HomeAssistant) -> None:
    username = PulsonClient("h", 8883, SID, "1234").username
    on_state = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/outputs", "1"),
            (f"system/{SID}/outputs/1/name", "Brama"),
            (f"system/{SID}/outputs/1/status", "1"),
        ],
    )
    await setup_with_state(hass, on_state)
    entity_id = find(hass, "brama")
    assert hass.states.get(entity_id).state == "on"
    with patch(
        "custom_components.pulson_alarm.client.PulsonClient.async_element_command",
        new=AsyncMock(),
    ) as command:
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True
        )
    assert command.await_args.args[0] == CMD_OUTPUT_OFF
    assert command.await_args.args[1] == "1"


async def test_output_unavailable_before_status_arrives(hass: HomeAssistant) -> None:
    """An output known only from the retained index list must not read 'off'."""
    username = PulsonClient("h", 8883, SID, "1234").username
    index_only = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/outputs", "1"),
            (f"system/{SID}/outputs/1/name", "Brama"),
        ],
    )
    await setup_with_state(hass, index_only)
    entity_id = find(hass, "brama")
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_bypass_switch_exists(hass: HomeAssistant) -> None:
    await setup_with_state(hass, state())
    assert any("bypass" in e for e in hass.states.async_entity_ids("switch"))


async def test_bypass_is_config_category(hass: HomeAssistant) -> None:
    await setup_with_state(hass, state())
    entity_id = find(hass, "bypass")
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None
    assert entry.entity_category == EntityCategory.CONFIG


async def test_bypass_turn_on_sends_block(hass: HomeAssistant) -> None:
    await setup_with_state(hass, state())
    entity_id = find(hass, "bypass")
    assert hass.states.get(entity_id).state == "off"
    with patch(
        "custom_components.pulson_alarm.client.PulsonClient.async_element_command",
        new=AsyncMock(),
    ) as command:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )
    assert command.await_args.args[0] == CMD_BLOCK
    assert command.await_args.args[1] == "2"


async def test_bypass_turn_off_sends_unblock(hass: HomeAssistant) -> None:
    username = PulsonClient("h", 8883, SID, "1234").username
    blocked_state = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/inputs", "2"),
            (f"system/{SID}/inputs/2/name", "Salon"),
            (f"system/{SID}/inputs/2/block", "1"),
            (f"system/{SID}/inputs/2/block_enable", "1"),
        ],
    )
    await setup_with_state(hass, blocked_state)
    entity_id = find(hass, "bypass")
    assert hass.states.get(entity_id).state == "on"
    with patch(
        "custom_components.pulson_alarm.client.PulsonClient.async_element_command",
        new=AsyncMock(),
    ) as command:
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True
        )
    assert command.await_args.args[0] == CMD_UNBLOCK
    assert command.await_args.args[1] == "2"


async def test_bypass_unavailable_when_not_allowed(hass: HomeAssistant) -> None:
    """The panel forbids bypassing this zone; the switch must not accept a command."""
    username = PulsonClient("h", 8883, SID, "1234").username
    forbidden_state = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/inputs", "2"),
            (f"system/{SID}/inputs/2/name", "Salon"),
            (f"system/{SID}/inputs/2/block", "0"),
            (f"system/{SID}/inputs/2/block_enable", "0"),
        ],
    )
    await setup_with_state(hass, forbidden_state)
    entity_id = find(hass, "bypass")
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_bypass_unavailable_before_block_arrives(hass: HomeAssistant) -> None:
    """A zone known only from the index list must not render bypass as 'off'."""
    username = PulsonClient("h", 8883, SID, "1234").username
    index_only = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/inputs", "2"),
            (f"system/{SID}/inputs/2/name", "Salon"),
        ],
    )
    await setup_with_state(hass, index_only)
    entity_id = find(hass, "bypass")
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
