"""Tests for the config flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pulson_alarm.client import PulsonAuthError, PulsonConnectionError
from custom_components.pulson_alarm.const import (
    CONF_PIN,
    CONF_QR,
    CONF_SYSTEM_ID,
    DOMAIN,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from homeassistant.core import HomeAssistant

QR = "1;solid.pulsonalarm.pl;8883;4321;00112233"


@pytest.fixture(autouse=True)
def _no_setup() -> Generator[AsyncMock]:
    with patch(
        "custom_components.pulson_alarm.async_setup_entry", return_value=True
    ) as mock:
        yield mock


async def _start(hass: HomeAssistant, step: str) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def test_qr_flow_creates_entry(hass: HomeAssistant) -> None:
    form = await _start(hass, "qr")
    with patch(
        "custom_components.pulson_alarm.config_flow.PulsonClient.async_verify",
        new=AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {CONF_QR: QR}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SYSTEM_ID] == "00112233"
    assert result["data"][CONF_PIN] == "4321"
    assert result["result"].unique_id == "00112233"


async def test_qr_flow_rejects_garbage(hass: HomeAssistant) -> None:
    form = await _start(hass, "qr")
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_QR: "nope"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_qr"}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PulsonAuthError("x"), "invalid_auth"),
        (PulsonConnectionError("x"), "cannot_connect"),
    ],
)
async def test_qr_flow_connection_errors(
    hass: HomeAssistant, error: Exception, expected: str
) -> None:
    form = await _start(hass, "qr")
    with patch(
        "custom_components.pulson_alarm.config_flow.PulsonClient.async_verify",
        new=AsyncMock(side_effect=error),
    ):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {CONF_QR: QR}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


def _suggested_value(schema: Any, key: str) -> Any:
    """Pull the suggested_value HA stashed on a schema marker's description."""
    for marker in schema.schema:
        if marker == key:
            if marker.description is None:
                return None
            return marker.description.get("suggested_value")
    raise KeyError(key)


async def test_qr_flow_invalid_auth_keeps_qr_input(hass: HomeAssistant) -> None:
    form = await _start(hass, "qr")
    with patch(
        "custom_components.pulson_alarm.config_flow.PulsonClient.async_verify",
        new=AsyncMock(side_effect=PulsonAuthError("x")),
    ):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {CONF_QR: QR}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "qr"
    assert result["errors"] == {"base": "invalid_auth"}
    assert _suggested_value(result["data_schema"], CONF_QR) == QR


async def test_manual_flow_cannot_connect_keeps_manual_input(
    hass: HomeAssistant,
) -> None:
    form = await _start(hass, "manual")
    with patch(
        "custom_components.pulson_alarm.config_flow.PulsonClient.async_verify",
        new=AsyncMock(side_effect=PulsonConnectionError("x")),
    ):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"],
            {"host": "h", CONF_SYSTEM_ID: "SID", CONF_PIN: "1", "port": 8883},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {"base": "cannot_connect"}
    assert _suggested_value(result["data_schema"], "host") == "h"
    assert _suggested_value(result["data_schema"], CONF_SYSTEM_ID) == "SID"


async def test_manual_flow_creates_entry(hass: HomeAssistant) -> None:
    form = await _start(hass, "manual")
    with patch(
        "custom_components.pulson_alarm.config_flow.PulsonClient.async_verify",
        new=AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"],
            {"host": "h", CONF_SYSTEM_ID: "SID", CONF_PIN: "1", "port": 8883},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_panel_aborts(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="00112233").add_to_hass(hass)
    form = await _start(hass, "qr")
    with patch(
        "custom_components.pulson_alarm.config_flow.PulsonClient.async_verify",
        new=AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {CONF_QR: QR}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


def _reauth_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="00112233",
        data={
            "host": "solid.pulsonalarm.pl",
            "port": 8883,
            CONF_SYSTEM_ID: "00112233",
            CONF_PIN: "4321",
        },
    )


async def test_reauth_with_good_pin_updates_entry_and_aborts(
    hass: HomeAssistant,
) -> None:
    """A successful reauth must update the stored PIN and reload the entry."""
    entry = _reauth_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    with patch(
        "custom_components.pulson_alarm.config_flow.PulsonClient.async_verify",
        new=AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PIN: "9999"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PIN] == "9999"
    assert entry.data[CONF_SYSTEM_ID] == "00112233"


async def test_reauth_with_bad_pin_shows_error(hass: HomeAssistant) -> None:
    """A rejected PIN must re-show the form with `invalid_auth`, entry untouched."""
    entry = _reauth_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)

    with patch(
        "custom_components.pulson_alarm.config_flow.PulsonClient.async_verify",
        new=AsyncMock(side_effect=PulsonAuthError("x")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PIN: "0000"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_PIN] == "4321"


async def test_reauth_cannot_connect_shows_error(hass: HomeAssistant) -> None:
    """A broker that cannot be reached must show `cannot_connect`, not crash."""
    entry = _reauth_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)

    with patch(
        "custom_components.pulson_alarm.config_flow.PulsonClient.async_verify",
        new=AsyncMock(side_effect=PulsonConnectionError("x")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PIN: "0000"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_PIN] == "4321"
