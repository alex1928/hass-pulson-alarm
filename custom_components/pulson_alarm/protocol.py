"""Pure PulsON cloud protocol.

Reverse-engineered for interoperability. This module MUST NOT import from
homeassistant so it stays unit-testable and extractable into a library.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import hashlib
from typing import Final

# Credential-derivation salts extracted from the vendor application.
_USER_PREFIX: Final = "fqCxoqb7ys6wX582fza0"
_USER_SALT: Final = "R9DmiPnoHEBVw9B39evU"
_PASS_PREFIX: Final = "oh2Zp9BVs7JlrP5q1Ik2"  # noqa: S105
_PASS_SALT: Final = "cX0EyPCvL5ZjEaTBIwhe"  # noqa: S105


def _md5(value: str) -> str:
    return hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()


def mqtt_username(system_id: str, pin: str) -> str:
    """Derive the broker username from the panel id and user PIN."""
    return f"{system_id}_" + _md5(f"{_USER_PREFIX}{pin}{_USER_SALT}")


def mqtt_password(system_id: str, pin: str) -> str:
    """Derive the broker password from the panel id and user PIN."""
    return _md5(f"{_PASS_PREFIX}{system_id}_{pin}{_PASS_SALT}")


MODULE_PARTITIONS: Final = "partitions"
MODULE_INPUTS: Final = "inputs"
MODULE_OUTPUTS: Final = "outputs"
MODULES: Final[tuple[str, ...]] = (MODULE_PARTITIONS, MODULE_INPUTS, MODULE_OUTPUTS)

# The panel publishes a value only once its exact leaf topic is subscribed;
# a '#' wildcard yields nothing but the retained index lists.
FIELDS: Final[dict[str, tuple[str, ...]]] = {
    MODULE_PARTITIONS: (
        "name",
        "status",
        "active",
        "night_mode",
        "alarm",
        "ready",
        "exit_time",
    ),
    MODULE_INPUTS: ("name", "status", "block", "block_enable"),
    MODULE_OUTPUTS: ("name", "status"),
}


def topic_index(system_id: str, username: str, module: str) -> str:
    """Retained CSV list of element ids for a module."""
    return f"system/{system_id}/users/{username}/{module}"


def topic_leaf(system_id: str, module: str, element_id: str, field: str) -> str:
    """Per-element state leaf. Note: no /users/ segment."""
    return f"system/{system_id}/{module}/{element_id}/{field}"


def topic_command(system_id: str, subtopic: str) -> str:
    """Command topic. Payload is always f'{pin}/{value}'."""
    return f"system/{system_id}/{subtopic}"


class PartitionState(IntEnum):
    """Values published on partitions/{id}/status."""

    DISARMED = 0
    ARMED = 1
    ARMED_NIGHT = 2
    ENTRY_TIME = 3
    EXIT_TIME = 4
    ALARM_INTRUDER = 5
    ALARM_FIRE = 6
    ALARM_GAS = 7
    ALARM_CO = 8
    ALARM_MEDICAL = 9
    ALARM_DEFINED = 10
    ALARM_TAMPER = 11
    ALARM_FLOOD = 12
    ALARM_TEMPERATURE = 13
    ENTRY_TIME_NIGHT = 14
    EXIT_TIME_NIGHT = 15
    ALARM_PANIC = 16
    ALARM_HOLDUP = 17
    ALARM_ZONE_TAMPER = 18
    ALARM_IN_MEMORY = 19


ALARM_STATES: Final[frozenset[int]] = frozenset(
    {
        PartitionState.ALARM_INTRUDER,
        PartitionState.ALARM_FIRE,
        PartitionState.ALARM_GAS,
        PartitionState.ALARM_CO,
        PartitionState.ALARM_MEDICAL,
        PartitionState.ALARM_DEFINED,
        PartitionState.ALARM_TAMPER,
        PartitionState.ALARM_FLOOD,
        PartitionState.ALARM_TEMPERATURE,
        PartitionState.ALARM_PANIC,
        PartitionState.ALARM_HOLDUP,
        PartitionState.ALARM_ZONE_TAMPER,
    }
)


class LineState(IntEnum):
    """Values published on inputs/{id}/status."""

    UNKNOWN = 0
    CLOSED = 1
    OPEN = 2
    TAMPER = 3
    FAULT = 4


# Command templates: (subtopic with {id}, payload value).
CMD_ARM_AWAY: Final[tuple[str, str]] = ("partitions/{id}/set_arm", "1")
CMD_ARM_NIGHT: Final[tuple[str, str]] = ("partitions/{id}/set_arm", "2")
CMD_DISARM: Final[tuple[str, str]] = ("partitions/{id}/set_disarm", "0")
CMD_BLOCK: Final[tuple[str, str]] = ("inputs/{id}/block_set", "1")
CMD_UNBLOCK: Final[tuple[str, str]] = ("inputs/{id}/block_set", "0")
CMD_OUTPUT_ON: Final[tuple[str, str]] = ("outputs/{id}/set", "1")
CMD_OUTPUT_OFF: Final[tuple[str, str]] = ("outputs/{id}/set", "0")
CMD_PANIC: Final[tuple[str, str]] = ("panic_alarm", "1")

_TRUE_VALUES: Final = frozenset({"1", "true", "on", "yes"})


def parse_bool(value: str | None) -> bool | None:
    """Panel booleans arrive as 'true'/'false' or '1'/'0'."""
    if value is None:
        return None
    return value.strip().lower() in _TRUE_VALUES


def parse_int(value: str | None) -> int | None:
    """Return the integer value, or None when the payload is not numeric."""
    if value is None:
        return None
    text = value.strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return None


@dataclass(frozen=True, slots=True)
class QrConfig:
    """Configuration carried by the panel QR payload."""

    host: str
    port: int
    pin: str
    system_id: str


_QR_FIELD_COUNT: Final = 5


def parse_qr(raw: str) -> QrConfig | None:
    """Parse '1;HOST;PORT;PIN;SYSTEM_ID' as printed by the panel keypad."""
    parts = [part.strip() for part in raw.strip().split(";")]
    if len(parts) < _QR_FIELD_COUNT:
        return None
    _, host, port, pin, system_id = parts[:_QR_FIELD_COUNT]
    if not host or not pin or not system_id or not port.isdigit():
        return None
    return QrConfig(host=host, port=int(port), pin=pin, system_id=system_id)
