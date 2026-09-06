"""Home Assistant facing constants. Wire protocol lives in protocol.py."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "pulson_alarm"
DEFAULT_PORT: Final = 8883

CONF_SYSTEM_ID: Final = "system_id"
CONF_PIN: Final = "pin"
CONF_QR: Final = "qr"

PLATFORMS: Final[list[Platform]] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
]

MANUFACTURER: Final = "PulsON (BCS Sp. z o.o.)"
MODEL: Final = "PulsON Alarm"
