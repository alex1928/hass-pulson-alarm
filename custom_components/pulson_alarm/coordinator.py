"""Push-only coordinator bridging the MQTT client to entities."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .models import EMPTY_STATE, PulsonState

if TYPE_CHECKING:
    from .client import PulsonClient

_LOGGER = logging.getLogger(__name__)

type PulsonConfigEntry = ConfigEntry[PulsonCoordinator]

_SHUTDOWN_TIMEOUT = 5


class PulsonCoordinator(DataUpdateCoordinator[PulsonState]):
    """Holds panel state. Never polls: the panel pushes after subscription."""

    config_entry: PulsonConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: PulsonConfigEntry, client: PulsonClient
    ) -> None:
        """Create a push-only coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            always_update=False,
        )
        self.client = client
        self.data = EMPTY_STATE
        self._task: asyncio.Task[None] | None = None

    async def async_start(self) -> None:
        """Launch the transport as a tracked background task."""
        self.client.set_client_id(f"ha-{self.config_entry.entry_id[:18]}")
        self._task = self.config_entry.async_create_background_task(
            self.hass,
            self.client.async_run(self._handle_state, self._handle_error),
            f"{DOMAIN}_mqtt_{self.config_entry.entry_id}",
        )

    async def async_shutdown(self) -> None:
        """Ask the transport to disconnect cleanly, then give up."""
        await self.client.async_stop()
        if self._task is not None:
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                async with asyncio.timeout(_SHUTDOWN_TIMEOUT):
                    await self._task
            self._task = None

    @callback
    def _handle_state(self, state: PulsonState) -> None:
        self.async_set_updated_data(state)

    @callback
    def _handle_error(self, err: Exception) -> None:
        self.async_set_update_error(err)
