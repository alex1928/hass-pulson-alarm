"""Switches: PGM outputs and per-zone bypass."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import PulsonClient
from .const import (
    CMD_BLOCK,
    CMD_OUTPUT_OFF,
    CMD_OUTPUT_ON,
    CMD_UNBLOCK,
    DOMAIN,
    parse_bool,
    parse_int,
)
from .entity import PulsonEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client: PulsonClient = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new: list[SwitchEntity] = []
        for oid in client.state.outputs:
            if f"out_{oid}" not in known:
                known.add(f"out_{oid}")
                new.append(PulsonOutput(client, oid))
        for lid in client.state.inputs:
            if f"bypass_{lid}" not in known:
                known.add(f"bypass_{lid}")
                new.append(PulsonBypass(client, lid))
        if new:
            async_add_entities(new)

    entry.async_on_unload(client.add_listener(_sync))
    _sync()


class PulsonOutput(PulsonEntity, SwitchEntity):
    """Programmable (PGM) output."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, client: PulsonClient, output_id: str) -> None:
        super().__init__(client)
        self.output_id = output_id
        self._attr_unique_id = f"{client.system_id}_output_{output_id}"

    @property
    def _data(self) -> dict[str, str]:
        return self._client.state.outputs.get(self.output_id, {})

    @property
    def name(self) -> str:
        return self._data.get("name") or f"Output {self.output_id}"

    @property
    def is_on(self) -> bool | None:
        status = parse_int(self._data.get("status"))
        if status is None:
            return None
        return status != 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.async_element_command(CMD_OUTPUT_ON, self.output_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.async_element_command(CMD_OUTPUT_OFF, self.output_id)


class PulsonBypass(PulsonEntity, SwitchEntity):
    """Bypass (block) a zone. On = zone bypassed."""

    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:shield-off-outline"

    def __init__(self, client: PulsonClient, line_id: str) -> None:
        super().__init__(client)
        self.line_id = line_id
        self._attr_unique_id = f"{client.system_id}_bypass_{line_id}"

    @property
    def _data(self) -> dict[str, str]:
        return self._client.state.inputs.get(self.line_id, {})

    @property
    def name(self) -> str:
        base = self._data.get("name") or f"Zone {self.line_id}"
        return f"{base} bypass"

    @property
    def is_on(self) -> bool | None:
        return parse_bool(self._data.get("block"))

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        allowed = parse_bool(self._data.get("block_enable"))
        return allowed is not False

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._client.async_element_command(CMD_BLOCK, self.line_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.async_element_command(CMD_UNBLOCK, self.line_id)
