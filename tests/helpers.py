"""Shared test helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulson_alarm.const import (
    CONF_PIN,
    CONF_SYSTEM_ID,
    DOMAIN,
    PLATFORMS,
)
from custom_components.pulson_alarm.models import (
    EMPTY_STATE,
    PulsonState,
    apply_message,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

SID = "SID"
PIN = "1234"


def build_state(username: str, messages: list[tuple[str, str]]) -> PulsonState:
    """Fold a list of (topic, payload) pairs into a state.

    Most tests pass this a complete set of messages - index, name and
    status together - and hand the result straight to `setup_with_state`,
    so entities are created only after everything has already arrived. Real
    hardware never does that: the retained index list always arrives before
    any per-element `name` or `status` leaf, because a leaf only starts
    publishing once its exact topic is subscribed. Collapsing that two-stage
    arrival here is fine for most tests, but it does mean entities in those
    tests are never seen in the state they're actually created in (`name`
    still `None`). The realistic ordering - and what it does to entity_id
    assignment - is covered separately by
    test_binary_sensor.py::test_entities_survive_the_realistic_two_stage_message_order.
    """
    state = EMPTY_STATE
    for topic, payload in messages:
        state = apply_message(state, topic, payload)
    return state


async def setup_with_state(
    hass: HomeAssistant,
    state: PulsonState,
    transport: dict[str, Any] | None = None,
) -> MockConfigEntry:
    """Set up the integration with a pre-seeded state and no real MQTT.

    Pass a dict as `transport` to capture the `on_state` / `on_error`
    callbacks the real MQTT loop would push through, so a test can simulate
    transport events (a drop, a reconnect) after setup.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "h", "port": 8883, CONF_SYSTEM_ID: SID, CONF_PIN: PIN},
        unique_id=SID,
    )
    entry.add_to_hass(hass)

    async def fake_run(_self, on_state, on_error) -> None:
        if transport is not None:
            transport["on_state"] = on_state
            transport["on_error"] = on_error
        on_state(state)

    with (
        patch(
            "custom_components.pulson_alarm.PulsonClient.async_verify", new=AsyncMock()
        ),
        patch(
            "custom_components.pulson_alarm.client.PulsonClient.async_run",
            new=fake_run,
        ),
        patch(
            "custom_components.pulson_alarm.PLATFORMS",
            PLATFORMS,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry
