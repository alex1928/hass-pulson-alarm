"""The PulsON Alarm integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .client import PulsonClient
from .const import CONF_PIN, CONF_SYSTEM_ID, DEFAULT_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PulsON Alarm from a config entry."""
    client = PulsonClient(
        host=entry.data[CONF_HOST],
        system_id=entry.data[CONF_SYSTEM_ID],
        pin=entry.data[CONF_PIN],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
    )

    try:
        await client.async_test_connection()
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryNotReady(f"Cannot reach PulsON cloud: {err}") from err

    await client.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        client: PulsonClient = hass.data[DOMAIN].pop(entry.entry_id)
        await client.async_stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
