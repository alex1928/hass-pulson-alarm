"""Tests for binary sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import STATE_UNAVAILABLE

from custom_components.pulson_alarm.client import PulsonClient
from tests.helpers import SID, build_state, setup_with_state

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def full_state():
    username = PulsonClient("h", 8883, SID, "1234").username
    return build_state(
        username,
        [
            (f"system/{SID}/users/{username}/partitions", "1"),
            (f"system/{SID}/users/{username}/inputs", "1"),
            (f"system/{SID}/partitions/1/name", "Parter"),
            (f"system/{SID}/partitions/1/status", "5"),
            (f"system/{SID}/inputs/1/name", "Drzwi wejściowe"),
            (f"system/{SID}/inputs/1/status", "2"),
            (f"system/{SID}/online/esp", "true"),
            (f"system/{SID}/online/simcom", "false"),
            (f"system/{SID}/programming", "1"),
        ],
    )


def find(hass: HomeAssistant, needle: str) -> str:
    matches = [e for e in hass.states.async_entity_ids("binary_sensor") if needle in e]
    assert matches, (
        f"no binary_sensor matching {needle!r} in "
        f"{hass.states.async_entity_ids('binary_sensor')}"
    )
    return matches[0]


async def test_zone_is_open_with_door_class(hass: HomeAssistant) -> None:
    await setup_with_state(hass, full_state())
    zone = hass.states.get(find(hass, "drzwi"))
    assert zone is not None
    assert zone.state == "on"
    assert zone.attributes["device_class"] == "door"


async def test_partition_alarm_on_when_triggered(hass: HomeAssistant) -> None:
    await setup_with_state(hass, full_state())
    # NB: a plain "alarm" needle would also match every other entity here,
    # since the device itself is named "PulsON Alarm" and that name is
    # folded into every entity_id. "parter_alarm" is unique to this sensor.
    alarm = hass.states.get(find(hass, "parter_alarm"))
    assert alarm is not None
    assert alarm.state == "on"
    assert alarm.attributes["device_class"] == "safety"


async def test_module_connectivity(hass: HomeAssistant) -> None:
    await setup_with_state(hass, full_state())
    assert hass.states.get(find(hass, "ip_wi_fi")).state == "on"
    assert hass.states.get(find(hass, "gsm")).state == "off"


async def test_programming_mode(hass: HomeAssistant) -> None:
    await setup_with_state(hass, full_state())
    assert hass.states.get(find(hass, "programming")).state == "on"


async def test_zone_unavailable_before_status_arrives(hass: HomeAssistant) -> None:
    """The index topic alone must not make the zone look 'unknown'.

    Mirrors the rule already enforced for partitions in
    test_alarm_control_panel.py::test_unavailable_before_status_arrives: a
    zone known only from the retained index list, with no per-element status
    leaf yet, must report unavailable rather than a stale/empty state (and,
    in particular, must never look like a closed door/window).
    """
    username = PulsonClient("h", 8883, SID, "1234").username
    state = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/inputs", "1"),
            (f"system/{SID}/inputs/1/name", "Drzwi wejściowe"),
        ],
    )
    await setup_with_state(hass, state)
    zone = hass.states.get(find(hass, "drzwi"))
    assert zone is not None
    assert zone.state == STATE_UNAVAILABLE


async def test_partition_alarm_unavailable_before_status_arrives(
    hass: HomeAssistant,
) -> None:
    """Same rule for the partition alarm sensor: no status yet means unavailable."""
    username = PulsonClient("h", 8883, SID, "1234").username
    state = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/partitions", "1"),
            (f"system/{SID}/partitions/1/name", "Parter"),
        ],
    )
    await setup_with_state(hass, state)
    alarm = hass.states.get(find(hass, "parter_alarm"))
    assert alarm is not None
    assert alarm.state == STATE_UNAVAILABLE


async def test_partition_alarm_unavailable_when_alarm_false_and_no_status(
    hass: HomeAssistant,
) -> None:
    """A false `alarm` leaf alone, with no `status` yet, must still be unavailable.

    `is_on` short-circuits on truthiness (`if data.alarm:`), not on
    not-None, so `alarm=False` with `status=None` falls through to
    `status is None` and would render `unknown` unless `available` mirrors
    that same truthiness check rather than an `is not None` check.
    """
    username = PulsonClient("h", 8883, SID, "1234").username
    state = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/partitions", "1"),
            (f"system/{SID}/partitions/1/name", "Parter"),
            (f"system/{SID}/partitions/1/alarm", "0"),
        ],
    )
    await setup_with_state(hass, state)
    alarm = hass.states.get(find(hass, "parter_alarm"))
    assert alarm is not None
    assert alarm.state == STATE_UNAVAILABLE


async def test_partition_alarm_on_from_alarm_flag_before_status_arrives(
    hass: HomeAssistant,
) -> None:
    """A true `alarm` leaf must surface immediately, even with no `status` yet.

    MQTT gives no ordering guarantee between the independent `alarm` flag
    and the `status` leaf, so a real alarm reported through `alarm` must not
    be masked by a stricter availability gate that waits on `status`.
    """
    username = PulsonClient("h", 8883, SID, "1234").username
    state = build_state(
        username,
        [
            (f"system/{SID}/users/{username}/partitions", "1"),
            (f"system/{SID}/partitions/1/name", "Parter"),
            (f"system/{SID}/partitions/1/alarm", "1"),
        ],
    )
    await setup_with_state(hass, state)
    alarm = hass.states.get(find(hass, "parter_alarm"))
    assert alarm is not None
    assert alarm.state == "on"
