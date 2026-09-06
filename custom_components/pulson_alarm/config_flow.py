"""Config flow placeholder.

Task 6 replaces this with the real ``PulsonConfigFlow`` (QR/manual steps).
This minimal stub exists only so the domain has a registered flow handler:
Home Assistant's ``ConfigEntry.async_setup`` unconditionally does
``integration.async_get_platform("config_flow")`` and then
``ConfigEntry.async_migrate`` unconditionally looks up
``config_entries.HANDLERS[domain]`` before ever calling into
``async_setup_entry`` -- both regardless of whether a flow is ever actually
started. Without this module and a registered handler, no config entry of
this domain can be set up at all, even in tests that build a
``MockConfigEntry`` directly.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class PulsonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Placeholder handler; Task 6 supplies the real steps."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Not implemented yet; Task 6 adds the qr/manual steps."""
        return self.async_abort(reason="not_implemented")
