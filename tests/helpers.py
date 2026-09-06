"""Shared test helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING
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


def build_state(username: str, messages: list[tuple[str, str]]) -> PulsonState:
    """Fold a list of (topic, payload) pairs into a state."""
    state = EMPTY_STATE
    for topic, payload in messages:
        state = apply_message(state, topic, payload)
    return state


async def setup_with_state(hass: HomeAssistant, state: PulsonState) -> MockConfigEntry:
    """Set up the integration with a pre-seeded state and no real MQTT."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "h", "port": 8883, CONF_SYSTEM_ID: SID, CONF_PIN: "1234"},
        unique_id=SID,
    )
    entry.add_to_hass(hass)

    async def fake_run(_self, on_state, on_error) -> None:
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
