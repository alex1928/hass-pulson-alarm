"""Config flow for PulsON Alarm."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
import voluptuous as vol

from .client import PulsonAuthError, PulsonClient, PulsonConnectionError
from .const import CONF_PIN, CONF_QR, CONF_SYSTEM_ID, DEFAULT_PORT, DOMAIN
from .protocol import parse_qr

if TYPE_CHECKING:
    from collections.abc import Mapping

QR_SCHEMA = vol.Schema({vol.Required(CONF_QR): str})
MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_SYSTEM_ID): str,
        vol.Required(CONF_PIN): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    }
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PIN): str})


class PulsonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PulsON Alarm."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick between the QR payload and manual entry."""
        return self.async_show_menu(step_id="user", menu_options=["qr", "manual"])

    async def async_step_qr(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Accept the QR payload printed by the panel keypad."""
        errors: dict[str, str] = {}
        if user_input is not None:
            parsed = parse_qr(user_input[CONF_QR])
            if parsed is None:
                errors["base"] = "invalid_qr"
            else:
                return await self._async_finish(
                    {
                        CONF_HOST: parsed.host,
                        CONF_PORT: parsed.port,
                        CONF_SYSTEM_ID: parsed.system_id,
                        CONF_PIN: parsed.pin,
                    },
                    "qr",
                    QR_SCHEMA,
                    user_input,
                )
        return self.async_show_form(step_id="qr", data_schema=QR_SCHEMA, errors=errors)

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Accept host, System ID and PIN typed by hand."""
        if user_input is not None:
            return await self._async_finish(
                dict(user_input), "manual", MANUAL_SCHEMA, user_input
            )
        return self.async_show_form(step_id="manual", data_schema=MANUAL_SCHEMA)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the broker rejects the stored PIN."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new PIN.

        Host and System ID come from the existing entry and are never taken
        from `user_input` here - the schema only exposes the PIN field - so a
        reauth can never repoint the entry at a different panel.
        """
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            client = PulsonClient(
                host=reauth_entry.data[CONF_HOST],
                port=reauth_entry.data.get(CONF_PORT, DEFAULT_PORT),
                system_id=reauth_entry.data[CONF_SYSTEM_ID],
                pin=user_input[CONF_PIN],
            )
            try:
                await client.async_verify()
            except PulsonAuthError:
                errors["base"] = "invalid_auth"
            except PulsonConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry, data_updates={CONF_PIN: user_input[CONF_PIN]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={
                CONF_SYSTEM_ID: reauth_entry.data[CONF_SYSTEM_ID]
            },
        )

    async def _async_finish(
        self,
        data: dict[str, Any],
        step_id: str,
        schema: vol.Schema,
        suggested_values: dict[str, Any],
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(data[CONF_SYSTEM_ID])
        self._abort_if_unique_id_configured()

        client = PulsonClient(
            host=data[CONF_HOST],
            port=data.get(CONF_PORT, DEFAULT_PORT),
            system_id=data[CONF_SYSTEM_ID],
            pin=data[CONF_PIN],
        )
        try:
            await client.async_verify()
        except PulsonAuthError:
            errors = {"base": "invalid_auth"}
        except PulsonConnectionError:
            errors = {"base": "cannot_connect"}
        else:
            return self.async_create_entry(
                title=f"PulsON {data[CONF_SYSTEM_ID][:8]}", data=data
            )
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested_values),
            errors=errors,
        )
