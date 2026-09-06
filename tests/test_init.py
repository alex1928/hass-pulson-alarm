"""Tests for setup and teardown of the config entry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulson_alarm.client import PulsonAuthError, PulsonConnectionError
from custom_components.pulson_alarm.const import CONF_PIN, CONF_SYSTEM_ID, DOMAIN
from custom_components.pulson_alarm.models import EMPTY_STATE
from tests.helpers import setup_with_state

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


async def test_runtime_auth_error_starts_reauth(hass: HomeAssistant) -> None:
    """A `PulsonAuthError` raised while already running must trigger reauth.

    `PulsonClient.async_run` reports the error and then simply returns (see
    client.py), so nothing retries on its own - a PIN changed on the keypad
    would otherwise leave the entry unavailable forever with no way back
    except deleting and re-adding it. The coordinator's error handler is
    what has to start reauth, since it is the one holding the config entry.
    """
    transport: dict[str, Any] = {}
    entry = await setup_with_state(hass, EMPTY_STATE, transport)

    transport["on_error"](PulsonAuthError("bad pin"))
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(
        flow["context"].get("source") == SOURCE_REAUTH
        and flow["context"].get("entry_id") == entry.entry_id
        for flow in flows
    )
