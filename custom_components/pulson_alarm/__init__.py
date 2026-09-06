"""The PulsON Alarm integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .client import PulsonAuthError, PulsonClient, PulsonConnectionError
from .const import CONF_PIN, CONF_SYSTEM_ID, DEFAULT_PORT, PLATFORMS
from .coordinator import PulsonConfigEntry, PulsonCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: PulsonConfigEntry) -> bool:
    """Set up PulsON Alarm from a config entry."""
    client = PulsonClient(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        system_id=entry.data[CONF_SYSTEM_ID],
        pin=entry.data[CONF_PIN],
    )

    try:
        await client.async_verify()
    except PulsonAuthError as err:
        raise ConfigEntryAuthFailed("Invalid System ID or PIN") from err
    except PulsonConnectionError as err:
        raise ConfigEntryNotReady("Cannot reach the PulsON cloud") from err

    coordinator = PulsonCoordinator(hass, entry, client)
    await coordinator.async_start()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PulsonConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
