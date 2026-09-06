"""Switches: PGM outputs and per-zone bypass."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory

from .entity import PulsonEntity, async_add_new
from .models import OutputData, ZoneData, known_ids
from .protocol import (
    CMD_BLOCK,
    CMD_OUTPUT_OFF,
    CMD_OUTPUT_ON,
    CMD_UNBLOCK,
    MODULE_INPUTS,
    MODULE_OUTPUTS,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import PulsonConfigEntry, PulsonCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PulsonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up output and bypass switches."""
    coordinator = entry.runtime_data

    def build_output(element_id: str) -> Iterable[PulsonEntity]:
        return [PulsonOutput(coordinator, element_id)]

    async_add_new(
        coordinator,
        entry,
        set(),
        lambda: known_ids(coordinator.data, MODULE_OUTPUTS),
        build_output,
        async_add_entities,
    )

    def build_bypass(element_id: str) -> Iterable[PulsonEntity]:
        return [PulsonBypass(coordinator, element_id)]

    async_add_new(
        coordinator,
        entry,
        set(),
        lambda: known_ids(coordinator.data, MODULE_INPUTS),
        build_bypass,
        async_add_entities,
    )


class PulsonOutput(PulsonEntity, SwitchEntity):
    """Programmable (PGM) output."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator: PulsonCoordinator, output_id: str) -> None:
        """Create the output switch."""
        super().__init__(coordinator)
        self.output_id = output_id
        self._attr_unique_id = f"{self._system_id}_output_{output_id}"

    @property
    def _data(self) -> OutputData:
        return self.coordinator.data.outputs.get(
            self.output_id, OutputData(id=self.output_id)
        )

    @property
    def available(self) -> bool:
        """Available once the panel has reported a status for this output.

        The retained index topic creates an `OutputData` with `status=None`
        before any per-element `status` leaf arrives. Treat that window as
        unavailable rather than surfacing a stale/empty "off" state (mirrors
        `_ZoneBase.available` in binary_sensor.py and `PulsonPartition.available`
        in alarm_control_panel.py).
        """
        return (
            super().available
            and self.output_id in self.coordinator.data.outputs
            and self._data.status is not None
        )

    @property
    def name(self) -> str:
        """Output name as configured on the panel."""
        return self._data.name or f"Output {self.output_id}"

    @property
    def is_on(self) -> bool | None:
        """True when the output is active."""
        status = self._data.status
        if status is None:
            return None
        return status != 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Activate the output."""
        await self.coordinator.client.async_element_command(
            CMD_OUTPUT_ON, self.output_id
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Deactivate the output."""
        await self.coordinator.client.async_element_command(
            CMD_OUTPUT_OFF, self.output_id
        )


class PulsonBypass(PulsonEntity, SwitchEntity):
    """Bypass a zone. On means the zone is bypassed."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:shield-off-outline"

    def __init__(self, coordinator: PulsonCoordinator, zone_id: str) -> None:
        """Create the bypass switch."""
        super().__init__(coordinator)
        self.zone_id = zone_id
        self._attr_unique_id = f"{self._system_id}_bypass_{zone_id}"

    @property
    def _data(self) -> ZoneData:
        return self.coordinator.data.zones.get(self.zone_id, ZoneData(id=self.zone_id))

    @property
    def name(self) -> str:
        """Zone name plus a bypass suffix."""
        return f"{self._data.name or f'Zone {self.zone_id}'} bypass"

    @property
    def is_on(self) -> bool | None:
        """True when the zone is bypassed."""
        return self._data.blocked

    @property
    def available(self) -> bool:
        """Unavailable before the panel reports a value, or until bypass is permitted.

        Duplicates the small "wait for a value from this zone" check that
        `_ZoneBase.available` in binary_sensor.py already performs (there
        keyed on `status`, here on `blocked`) rather than importing that
        module-private class: the shared logic is a couple of lines, the two
        entities key off different fields, and `PulsonPartition` in
        alarm_control_panel.py already duplicates the same shape rather than
        sharing it, so this follows existing precedent. On top of that base
        check, the panel is the sole authority on whether a zone may be
        bypassed at all: the switch stays unavailable until `block_allowed`
        has been affirmatively reported `True`. A zone whose `block_allowed`
        has never arrived (still `None`) is treated the same as one that
        explicitly forbids it, not as permissive — MQTT gives no ordering
        guarantee between the `block` and `block_enable` topics, so briefly
        having one without the other is a real window, and offering a
        security-relevant control before permission is confirmed is the
        wrong default (the panel may then silently refuse the command).
        """
        if not super().available or self.zone_id not in self.coordinator.data.zones:
            return False
        data = self._data
        if data.blocked is None:
            return False
        return data.block_allowed is True

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Bypass the zone."""
        await self.coordinator.client.async_element_command(CMD_BLOCK, self.zone_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop bypassing the zone."""
        await self.coordinator.client.async_element_command(CMD_UNBLOCK, self.zone_id)
