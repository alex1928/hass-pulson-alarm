"""Shared entity base for PulsON Alarm."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .client import PulsonClient
from .const import DOMAIN


class PulsonEntity(Entity):
    """Base entity: push-driven, no polling."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, client: PulsonClient) -> None:
        self._client = client
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, client.system_id)},
            manufacturer="PulsON (BCS Sp. z o.o.)",
            model="PulsON Alarm",
            name="PulsON Alarm",
            configuration_url=f"https://{client.host}",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.add_listener(self._handle_update))

    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._client.connected
