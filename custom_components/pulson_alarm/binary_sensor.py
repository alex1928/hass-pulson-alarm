"""Binary sensors: zones, zone faults, partition alarms, module connectivity."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import PulsonClient
from .const import (
    ALARM_STATES,
    DOMAIN,
    LINE_STATE_NAMES,
    LineState,
    parse_bool,
    parse_int,
)
from .entity import PulsonEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    client: PulsonClient = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    static = [
        PulsonProgramming(client),
        PulsonModuleOnline(client, "esp", "IP / Wi-Fi module"),
        PulsonModuleOnline(client, "simcom", "GSM module"),
    ]
    async_add_entities(static)

    @callback
    def _sync() -> None:
        new: list[BinarySensorEntity] = []
        for lid in client.state.inputs:
            if f"zone_{lid}" not in known:
                known.add(f"zone_{lid}")
                new.append(PulsonZone(client, lid))
                new.append(PulsonZoneProblem(client, lid))
        for pid in client.state.partitions:
            if f"alarm_{pid}" not in known:
                known.add(f"alarm_{pid}")
                new.append(PulsonPartitionAlarm(client, pid))
        if new:
            async_add_entities(new)

    entry.async_on_unload(client.add_listener(_sync))
    _sync()


class PulsonZone(PulsonEntity, BinarySensorEntity):
    """Zone open/closed."""

    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(self, client: PulsonClient, line_id: str) -> None:
        super().__init__(client)
        self.line_id = line_id
        self._attr_unique_id = f"{client.system_id}_zone_{line_id}"

    @property
    def _data(self) -> dict[str, str]:
        return self._client.state.inputs.get(self.line_id, {})

    @property
    def name(self) -> str:
        return self._data.get("name") or f"Zone {self.line_id}"

    @property
    def is_on(self) -> bool | None:
        status = parse_int(self._data.get("status"))
        if status is None:
            return None
        return status == LineState.OPEN

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        data = self._data
        status = parse_int(data.get("status"))
        return {
            "raw_status": status,
            "status_name": LINE_STATE_NAMES.get(status, "unknown"),
            "bypassed": parse_bool(data.get("block")),
            "bypass_allowed": parse_bool(data.get("block_enable")),
        }


class PulsonZoneProblem(PulsonEntity, BinarySensorEntity):
    """Zone tamper/fault."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_registry_enabled_default = False

    def __init__(self, client: PulsonClient, line_id: str) -> None:
        super().__init__(client)
        self.line_id = line_id
        self._attr_unique_id = f"{client.system_id}_zone_{line_id}_problem"

    @property
    def name(self) -> str:
        data = self._client.state.inputs.get(self.line_id, {})
        base = data.get("name") or f"Zone {self.line_id}"
        return f"{base} problem"

    @property
    def is_on(self) -> bool | None:
        status = parse_int(self._client.state.inputs.get(self.line_id, {}).get("status"))
        if status is None:
            return None
        return status in (LineState.TAMPER, LineState.FAULT)


class PulsonPartitionAlarm(PulsonEntity, BinarySensorEntity):
    """Alarm active in a partition."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, client: PulsonClient, partition_id: str) -> None:
        super().__init__(client)
        self.partition_id = partition_id
        self._attr_unique_id = f"{client.system_id}_partition_{partition_id}_alarm"

    @property
    def name(self) -> str:
        data = self._client.state.partitions.get(self.partition_id, {})
        base = data.get("name") or f"Partition {self.partition_id}"
        return f"{base} alarm"

    @property
    def is_on(self) -> bool | None:
        data = self._client.state.partitions.get(self.partition_id, {})
        if parse_bool(data.get("alarm")):
            return True
        status = parse_int(data.get("status"))
        if status is None:
            return None
        return status in ALARM_STATES


class PulsonModuleOnline(PulsonEntity, BinarySensorEntity):
    """ESP (IP/Wi-Fi) or SimCom (GSM) module connectivity."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, client: PulsonClient, key: str, label: str) -> None:
        super().__init__(client)
        self._key = key
        self._attr_name = label
        self._attr_unique_id = f"{client.system_id}_online_{key}"

    @property
    def is_on(self) -> bool | None:
        return parse_bool(self._client.state.online.get(self._key))


class PulsonProgramming(PulsonEntity, BinarySensorEntity):
    """Installer programming (service) mode - read-only."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Installer programming mode"

    def __init__(self, client: PulsonClient) -> None:
        super().__init__(client)
        self._attr_unique_id = f"{client.system_id}_programming"

    @property
    def is_on(self) -> bool | None:
        return self._client.state.programming
