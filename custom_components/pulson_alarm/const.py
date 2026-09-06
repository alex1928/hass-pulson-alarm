"""Constants and protocol definitions for the PulsON Alarm integration."""

from __future__ import annotations

import hashlib
from typing import Final

DOMAIN: Final = "pulson_alarm"
DEFAULT_PORT: Final = 8883
KEEPALIVE: Final = 10

CONF_SYSTEM_ID: Final = "system_id"
CONF_PIN: Final = "pin"
CONF_QR: Final = "qr"

# Credential-derivation salts (extracted from the vendor app, required for interoperability).
_USER_PREFIX: Final = "fqCxoqb7ys6wX582fza0"
_USER_SALT: Final = "R9DmiPnoHEBVw9B39evU"
_PASS_PREFIX: Final = "oh2Zp9BVs7JlrP5q1Ik2"
_PASS_SALT: Final = "cX0EyPCvL5ZjEaTBIwhe"


def _md5(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()  # noqa: S324 - protocol-mandated


def mqtt_username(system_id: str, pin: str) -> str:
    """Derive the broker username for a panel/user pair."""
    return f"{system_id}_" + _md5(f"{_USER_PREFIX}{pin}{_USER_SALT}")


def mqtt_password(system_id: str, pin: str) -> str:
    """Derive the broker password for a panel/user pair."""
    return _md5(f"{_PASS_PREFIX}{system_id}_{pin}{_PASS_SALT}")


# --- topics -----------------------------------------------------------------
MODULE_PARTITIONS: Final = "partitions"
MODULE_INPUTS: Final = "inputs"
MODULE_OUTPUTS: Final = "outputs"
MODULES: Final = (MODULE_PARTITIONS, MODULE_INPUTS, MODULE_OUTPUTS)

# Fields published per element. The panel only publishes a value once the exact
# leaf topic is subscribed - a '#' wildcard does NOT trigger publication.
FIELDS: Final[dict[str, tuple[str, ...]]] = {
    MODULE_PARTITIONS: ("name", "status", "active", "night_mode", "alarm", "ready", "exit_time"),
    MODULE_INPUTS: ("name", "status", "block", "block_enable"),
    MODULE_OUTPUTS: ("name", "status"),
}


def topic_index(system_id: str, username: str, module: str) -> str:
    """Retained CSV list of element ids for a module."""
    return f"system/{system_id}/users/{username}/{module}"


def topic_leaf(system_id: str, module: str, element_id: str, field: str) -> str:
    """Per-element state leaf (note: no /users/ segment)."""
    return f"system/{system_id}/{module}/{element_id}/{field}"


def topic_command(system_id: str, subtopic: str) -> str:
    return f"system/{system_id}/{subtopic}"


# --- enums ------------------------------------------------------------------
class PartitionState:
    """Values of partitions/{id}/status."""

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


ALARM_STATES: Final = frozenset(
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

PARTITION_STATE_NAMES: Final[dict[int, str]] = {
    0: "disarmed", 1: "armed_away", 2: "armed_night", 3: "entry_time", 4: "exit_time",
    5: "alarm_intruder", 6: "alarm_fire", 7: "alarm_gas", 8: "alarm_co",
    9: "alarm_medical", 10: "alarm_defined", 11: "alarm_tamper", 12: "alarm_flood",
    13: "alarm_temperature", 14: "entry_time_night", 15: "exit_time_night",
    16: "alarm_panic", 17: "alarm_holdup", 18: "alarm_zone_tamper", 19: "alarm_in_memory",
}


class LineState:
    """Values of inputs/{id}/status."""

    UNKNOWN = 0
    CLOSED = 1
    OPEN = 2
    TAMPER = 3
    FAULT = 4


LINE_STATE_NAMES: Final[dict[int, str]] = {
    0: "unknown", 1: "closed", 2: "open", 3: "tamper", 4: "fault",
}

# --- commands ---------------------------------------------------------------
CMD_ARM_AWAY: Final = ("partitions/{id}/set_arm", "1")
CMD_ARM_NIGHT: Final = ("partitions/{id}/set_arm", "2")
CMD_DISARM: Final = ("partitions/{id}/set_disarm", "0")
CMD_BLOCK: Final = ("inputs/{id}/block_set", "1")
CMD_UNBLOCK: Final = ("inputs/{id}/block_set", "0")
CMD_OUTPUT_ON: Final = ("outputs/{id}/set", "1")
CMD_OUTPUT_OFF: Final = ("outputs/{id}/set", "0")
CMD_PANIC: Final = ("panic_alarm", "1")


def parse_bool(value: str | None) -> bool | None:
    """Panel booleans arrive as 'true'/'false' or '1'/'0'."""
    if value is None:
        return None
    return str(value).strip().lower() in ("1", "true", "on", "yes")


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return None


def parse_qr(raw: str) -> dict[str, str] | None:
    """Parse the panel QR payload: '1;HOST;PORT;PIN;SYSTEM_ID'."""
    parts = [p.strip() for p in raw.strip().split(";")]
    if len(parts) < 5:
        return None
    return {"host": parts[1], "port": parts[2], "pin": parts[3], "system_id": parts[4]}
