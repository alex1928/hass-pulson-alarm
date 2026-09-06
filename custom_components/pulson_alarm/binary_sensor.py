"""Binary sensors: zones, zone faults, partition alarms, module connectivity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory

from .entity import PulsonEntity, async_add_new
from .heuristics import guess_device_class
from .models import PartitionData, ZoneData, known_ids
from .protocol import ALARM_STATES, MODULE_INPUTS, MODULE_PARTITIONS, LineState

if TYPE_CHECKING:
    from collections.abc import Iterable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import PulsonConfigEntry, PulsonCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PulsonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up zone, partition-alarm and diagnostic binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            PulsonModuleOnline(coordinator, "esp", "IP / Wi-Fi module"),
            PulsonModuleOnline(coordinator, "simcom", "GSM module"),
            PulsonProgramming(coordinator),
        ]
    )

    def build_zone(element_id: str) -> Iterable[PulsonEntity]:
        return [
            PulsonZone(coordinator, element_id),
            PulsonZoneProblem(coordinator, element_id),
        ]

    async_add_new(
        coordinator,
        entry,
        set(),
        lambda: known_ids(coordinator.data, MODULE_INPUTS),
        build_zone,
        async_add_entities,
    )

    def build_alarm(element_id: str) -> Iterable[PulsonEntity]:
        return [PulsonPartitionAlarm(coordinator, element_id)]

    async_add_new(
        coordinator,
        entry,
        set(),
        lambda: known_ids(coordinator.data, MODULE_PARTITIONS),
        build_alarm,
        async_add_entities,
    )


class _ZoneBase(PulsonEntity, BinarySensorEntity):
    """Shared zone lookup."""

    def __init__(self, coordinator: PulsonCoordinator, zone_id: str) -> None:
        """Store the zone id."""
        super().__init__(coordinator)
        self.zone_id = zone_id

    @property
    def _data(self) -> ZoneData:
        return self.coordinator.data.zones.get(self.zone_id, ZoneData(id=self.zone_id))

    @property
    def available(self) -> bool:
        """Available once the panel has reported a status for this zone.

        The retained index topic creates a `ZoneData` with `status=None`
        before any per-element `status` leaf arrives. Treat that window as
        unavailable rather than surfacing a stale/empty state (mirrors
        `PulsonPartition.available` in alarm_control_panel.py).
        """
        return (
            super().available
            and self.zone_id in self.coordinator.data.zones
            and self._data.status is not None
        )


class PulsonZone(_ZoneBase):
    """Zone open/closed."""

    def __init__(self, coordinator: PulsonCoordinator, zone_id: str) -> None:
        """Create the zone sensor."""
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = f"{self._system_id}_zone_{zone_id}"

    @property
    def name(self) -> str:
        """Zone name as configured on the panel."""
        return self._data.name or f"Zone {self.zone_id}"

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        """Guessed from the zone name."""
        return guess_device_class(self._data.name)

    @property
    def is_on(self) -> bool | None:
        """True when the zone is violated, None when the panel cannot tell.

        Only CLOSED is evidence of a secure zone. UNKNOWN, TAMPER and FAULT
        say the panel has lost sight of the line - a cut detector cable must
        never render as a securely closed door - so they report `unknown`
        here and are surfaced by the companion problem sensor instead.
        """
        status = self._data.status
        if status == LineState.OPEN:
            return True
        if status == LineState.CLOSED:
            return False
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Raw status and bypass information."""
        data = self._data
        return {
            "raw_status": data.status,
            "bypassed": data.blocked,
            "bypass_allowed": data.block_allowed,
        }


class PulsonZoneProblem(_ZoneBase):
    """Zone tamper or fault."""

    # Enabled by default on purpose: `PulsonZone.is_on` reports `unknown` for
    # TAMPER and FAULT rather than guessing, so this sensor is the only place
    # a sabotaged or broken zone is visible.
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PulsonCoordinator, zone_id: str) -> None:
        """Create the zone problem sensor."""
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = f"{self._system_id}_zone_{zone_id}_problem"

    @property
    def name(self) -> str:
        """Zone name plus a problem suffix."""
        return f"{self._data.name or f'Zone {self.zone_id}'} problem"

    @property
    def is_on(self) -> bool | None:
        """True on tamper or fault."""
        status = self._data.status
        if status is None:
            return None
        return status in (LineState.TAMPER, LineState.FAULT)


class PulsonPartitionAlarm(PulsonEntity, BinarySensorEntity):
    """Alarm active in a partition."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, coordinator: PulsonCoordinator, partition_id: str) -> None:
        """Create the partition alarm sensor."""
        super().__init__(coordinator)
        self.partition_id = partition_id
        self._attr_unique_id = f"{self._system_id}_partition_{partition_id}_alarm"

    @property
    def _data(self) -> PartitionData:
        return self.coordinator.data.partitions.get(
            self.partition_id, PartitionData(id=self.partition_id)
        )

    @property
    def available(self) -> bool:
        """Available once the panel has reported *some* alarm signal.

        The retained index topic alone must not make this look like a stale
        "no alarm" reading (mirrors `PulsonPartition.available` in
        alarm_control_panel.py). Unlike that plain status entity, `is_on`
        here can resolve from `alarm` alone before `status` ever arrives, so
        gate on "neither has arrived yet" rather than on `status`
        specifically - requiring `status` would risk masking a real alarm
        reported through the independent `alarm` flag.
        """
        data = self._data
        return (
            super().available
            and self.partition_id in self.coordinator.data.partitions
            and (data.alarm or data.status is not None)
        )

    @property
    def name(self) -> str:
        """Partition name plus an alarm suffix."""
        return f"{self._data.name or f'Partition {self.partition_id}'} alarm"

    @property
    def is_on(self) -> bool | None:
        """True when the partition reports an alarm."""
        data = self._data
        if data.alarm:
            return True
        if data.status is None:
            return None
        return data.status in ALARM_STATES


class PulsonModuleOnline(PulsonEntity, BinarySensorEntity):
    """Connectivity of the IP or GSM communication module."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PulsonCoordinator, key: str, label: str) -> None:
        """Create the module connectivity sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_name = label
        self._attr_unique_id = f"{self._system_id}_online_{key}"

    @property
    def is_on(self) -> bool | None:
        """True when the module reports online."""
        return self.coordinator.data.modules_online.get(self._key)


class PulsonProgramming(PulsonEntity, BinarySensorEntity):
    """Installer programming (service) mode. Read-only."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_name = "Installer programming mode"

    def __init__(self, coordinator: PulsonCoordinator) -> None:
        """Create the programming mode sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self._system_id}_programming"

    @property
    def is_on(self) -> bool | None:
        """True while the installer holds the panel in programming mode."""
        return self.coordinator.data.programming
