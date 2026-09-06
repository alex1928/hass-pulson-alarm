"""Shared test helpers."""

from __future__ import annotations

from importlib import util as importlib_util
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


def _implemented_platforms() -> list[str]:
    """Platforms declared in const.PLATFORMS whose module already exists.

    The plan lands one platform module per task while const.PLATFORMS already
    lists the full target set, so forwarding entry setup to a not-yet-written
    platform would raise ModuleNotFoundError. Filtering here keeps this
    helper usable, unmodified, by every task's tests as platforms are added.
    """
    return [
        platform
        for platform in PLATFORMS
        if importlib_util.find_spec(f"custom_components.pulson_alarm.{platform}")
        is not None
    ]


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
            _implemented_platforms(),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry
