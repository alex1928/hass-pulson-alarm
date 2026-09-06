"""Config flow for PulsON Alarm."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .client import PulsonClient
from .const import CONF_PIN, CONF_QR, CONF_SYSTEM_ID, DEFAULT_PORT, DOMAIN, parse_qr

_LOGGER = logging.getLogger(__name__)

QR_SCHEMA = vol.Schema({vol.Required(CONF_QR): str})

MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_SYSTEM_ID): str,
        vol.Required(CONF_PIN): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)


class PulsonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the PulsON Alarm config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Paste the panel QR payload: '1;HOST;PORT;PIN;SYSTEM_ID'."""
        errors: dict[str, str] = {}
        if user_input is not None:
            parsed = parse_qr(user_input[CONF_QR])
            if parsed is None:
                errors["base"] = "invalid_qr"
            else:
                port = int(parsed["port"]) if parsed["port"].isdigit() else DEFAULT_PORT
                return await self._async_validate_and_create(
                    {
                        CONF_HOST: parsed["host"],
                        CONF_SYSTEM_ID: parsed["system_id"],
                        CONF_PIN: parsed["pin"],
                        CONF_PORT: port,
                    },
                    errors,
                    QR_SCHEMA,
                    "user",
                )
        return self.async_show_form(
            step_id="user", data_schema=QR_SCHEMA, errors=errors
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter host / system id / PIN by hand."""
        errors: dict[str, str] = {}
        if user_input is not None:
            return await self._async_validate_and_create(
                dict(user_input), errors, MANUAL_SCHEMA, "manual"
            )
        return self.async_show_form(
            step_id="manual", data_schema=MANUAL_SCHEMA, errors=errors
        )

    async def _async_validate_and_create(
        self,
        data: dict[str, Any],
        errors: dict[str, str],
        schema: vol.Schema,
        step_id: str,
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(data[CONF_SYSTEM_ID])
        self._abort_if_unique_id_configured()

        client = PulsonClient(
            host=data[CONF_HOST],
            system_id=data[CONF_SYSTEM_ID],
            pin=data[CONF_PIN],
            port=data.get(CONF_PORT, DEFAULT_PORT),
        )
        try:
            await client.async_test_connection()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("PulsON connection test failed: %s", err)
            text = str(err).lower()
            if "not authorised" in text or "not authorized" in text or "password" in text:
                errors["base"] = "invalid_auth"
            else:
                errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id=step_id, data_schema=schema, errors=errors
            )

        return self.async_create_entry(
            title=f"PulsON {data[CONF_SYSTEM_ID][:8]}", data=data
        )
