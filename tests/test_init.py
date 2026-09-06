"""Tests for setup and teardown of the config entry."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulson_alarm.client import PulsonAuthError, PulsonConnectionError
from custom_components.pulson_alarm.const import CONF_PIN, CONF_SYSTEM_ID, DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

ENTRY_DATA = {
    "host": "h",
    "port": 8883,
    CONF_SYSTEM_ID: "SID",
    CONF_PIN: "1234",
}


def make_entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="SID")


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.pulson_alarm.PulsonClient.async_verify",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.pulson_alarm.PulsonClient.async_run",
            new=AsyncMock(),
        ),
        # Platform forwarding is proven by each platform's own tests (Tasks 7-9);
        # this test only owns the coordinator lifecycle, so no real platform
        # modules need to exist for it to pass.
        patch("custom_components.pulson_alarm.PLATFORMS", []),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PulsonConnectionError("x"), ConfigEntryState.SETUP_RETRY),
        (PulsonAuthError("x"), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_setup_failures(
    hass: HomeAssistant, error: Exception, expected: ConfigEntryState
) -> None:
    entry = make_entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.pulson_alarm.PulsonClient.async_verify",
        new=AsyncMock(side_effect=error),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is expected
