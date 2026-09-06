"""Alarm control panel entities (one per partition)."""

from __future__ import annotations

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import PulsonClient
from .const import (
    ALARM_STATES,
    CMD_ARM_AWAY,
    CMD_ARM_NIGHT,
    CMD_DISARM,
    DOMAIN,
    PARTITION_STATE_NAMES,
    PartitionState,
    parse_bool,
    parse_int,
)
from .entity import PulsonEntity

STATE_MAP: dict[int, AlarmControlPanelState] = {
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
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up partitions, adding new ones as the panel reports them."""
    client: PulsonClient = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _sync() -> None:
        new = [
            PulsonPartition(client, pid)
            for pid in client.state.partitions
            if pid not in known
        ]
        if new:
            known.update(e.partition_id for e in new)
            async_add_entities(new)

    entry.async_on_unload(client.add_listener(_sync))
    _sync()


class PulsonPartition(PulsonEntity, AlarmControlPanelEntity):
    """A PulsON partition."""

    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_NIGHT
    )
    _attr_code_arm_required = False

    def __init__(self, client: PulsonClient, partition_id: str) -> None:
        super().__init__(client)
        self.partition_id = partition_id
        self._attr_unique_id = f"{client.system_id}_partition_{partition_id}"

    @property
    def _data(self) -> dict[str, str]:
        return self._client.state.partitions.get(self.partition_id, {})

    @property
    def name(self) -> str:
        return self._data.get("name") or f"Partition {self.partition_id}"

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        status = parse_int(self._data.get("status"))
        if status is None:
            return None
        if status in ALARM_STATES:
            return AlarmControlPanelState.TRIGGERED
        return STATE_MAP.get(status)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        data = self._data
        status = parse_int(data.get("status"))
        attrs: dict[str, object] = {
            "raw_status": status,
            "status_name": PARTITION_STATE_NAMES.get(status, "unknown"),
            "ready": parse_bool(data.get("ready")),
            "alarm": parse_bool(data.get("alarm")),
            "alarm_in_memory": status == PartitionState.ALARM_IN_MEMORY,
            # config flags, not live state
            "active": parse_bool(data.get("active")),
            "night_mode_available": parse_bool(data.get("night_mode")),
        }
        if status in (PartitionState.EXIT_TIME, PartitionState.EXIT_TIME_NIGHT):
            attrs["exit_time"] = parse_int(data.get("exit_time"))
        return attrs

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        await self._client.async_element_command(CMD_DISARM, self.partition_id)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._client.async_element_command(CMD_ARM_AWAY, self.partition_id)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        await self._client.async_element_command(CMD_ARM_NIGHT, self.partition_id)
