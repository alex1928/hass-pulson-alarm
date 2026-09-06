"""Alarm control panel entities, one per partition."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from homeassistant.components.alarm_control_panel import AlarmControlPanelEntity
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)

from .entity import PulsonEntity, async_add_new
from .models import PartitionData, known_ids
from .protocol import (
    ALARM_STATES,
    CMD_ARM_AWAY,
    CMD_ARM_NIGHT,
    CMD_DISARM,
    MODULE_PARTITIONS,
    PartitionState,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import PulsonConfigEntry, PulsonCoordinator

PARALLEL_UPDATES = 1

_STATE_MAP: Final[dict[int, AlarmControlPanelState]] = {
    PartitionState.DISARMED: AlarmControlPanelState.DISARMED,
    PartitionState.ARMED: AlarmControlPanelState.ARMED_AWAY,
    PartitionState.ARMED_NIGHT: AlarmControlPanelState.ARMED_NIGHT,
    PartitionState.ENTRY_TIME: AlarmControlPanelState.PENDING,
    PartitionState.ENTRY_TIME_NIGHT: AlarmControlPanelState.PENDING,
    PartitionState.EXIT_TIME: AlarmControlPanelState.ARMING,
    PartitionState.EXIT_TIME_NIGHT: AlarmControlPanelState.ARMING,
    PartitionState.ALARM_IN_MEMORY: AlarmControlPanelState.DISARMED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PulsonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one alarm panel per partition."""
    coordinator = entry.runtime_data

    def build(element_id: str) -> Iterable[PulsonEntity]:
        return [PulsonPartition(coordinator, element_id)]

    async_add_new(
        coordinator,
        entry,
        set(),
        lambda: known_ids(coordinator.data, MODULE_PARTITIONS),
        build,
        async_add_entities,
    )


class PulsonPartition(PulsonEntity, AlarmControlPanelEntity):
    """One PulsON partition."""

    _attr_name = None
    _attr_code_format = CodeFormat.NUMBER
    _attr_code_arm_required = False
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_NIGHT
    )

    def __init__(self, coordinator: PulsonCoordinator, partition_id: str) -> None:
        """Create the partition entity."""
        super().__init__(coordinator)
        self.partition_id = partition_id
        self._attr_unique_id = f"{self._system_id}_partition_{partition_id}"

    @property
    def _data(self) -> PartitionData:
        return self.coordinator.data.partitions.get(
            self.partition_id, PartitionData(id=self.partition_id)
        )

    @property
    def available(self) -> bool:
        """Only available once the panel has reported this partition."""
        return (
            super().available and self.partition_id in self.coordinator.data.partitions
        )

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Map the panel status enum onto Home Assistant states."""
        status = self._data.status
        if status is None:
            return None
        if status in ALARM_STATES:
            return AlarmControlPanelState.TRIGGERED
        return _STATE_MAP.get(status)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose raw and configuration values not modelled as entities."""
        data = self._data
        attributes: dict[str, Any] = {
            "raw_status": data.status,
            "ready": data.ready,
            "alarm": data.alarm,
            "alarm_in_memory": data.status == PartitionState.ALARM_IN_MEMORY,
            "active": data.active,
            "night_mode_available": data.night_mode,
        }
        if data.status in (PartitionState.EXIT_TIME, PartitionState.EXIT_TIME_NIGHT):
            attributes["exit_time"] = data.exit_time
        return attributes

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Disarm the partition."""
        await self.coordinator.client.async_element_command(
            CMD_DISARM, self.partition_id
        )

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Arm the partition in away mode."""
        await self.coordinator.client.async_element_command(
            CMD_ARM_AWAY, self.partition_id
        )

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Arm the partition in night mode."""
        await self.coordinator.client.async_element_command(
            CMD_ARM_NIGHT, self.partition_id
        )
