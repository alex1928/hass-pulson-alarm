"""Tests for binary sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.pulson_alarm.client import PulsonClient
from custom_components.pulson_alarm.protocol import LineState
from tests.helpers import PIN, SID, build_state, setup_with_state

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def full_state():
    username = PulsonClient("h", 8883, SID, PIN).username
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


def find(hass: HomeAssistant, suffix: str) -> str:
    """Return the one binary_sensor entity id ending in `suffix`.

    Suffix matching, and an exactness assert, rather than the substring
    "first match wins" this used to do: now that the zone problem sensor
    ships enabled, a zone's own id is a prefix of its problem sensor's id and
    a substring search would silently return whichever happened to come first.
    """
    all_ids = hass.states.async_entity_ids("binary_sensor")
    matches = [entity_id for entity_id in all_ids if entity_id.endswith(suffix)]
    assert len(matches) == 1, (
        f"expected exactly one binary_sensor ending in {suffix!r}, "
        f"got {matches} out of {all_ids}"
    )
    return matches[0]


async def test_zone_is_open_with_door_class(hass: HomeAssistant) -> None:
    await setup_with_state(hass, full_state())
    zone = hass.states.get(find(hass, "drzwi_wejsciowe"))
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
    assert hass.states.get(find(hass, "ip_wi_fi_module")).state == "on"
    assert hass.states.get(find(hass, "gsm_module")).state == "off"


async def test_programming_mode(hass: HomeAssistant) -> None:
    await setup_with_state(hass, full_state())
    assert hass.states.get(find(hass, "programming_mode")).state == "on"


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
    zone = hass.states.get(find(hass, "drzwi_wejsciowe"))
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


def zone_state(status: str):
    """Build a state with one named zone reporting `status` on its input line."""
    username = PulsonClient("h", 8883, SID, PIN).username
    return build_state(
        username,
        [
            (f"system/{SID}/users/{username}/inputs", "1"),
            (f"system/{SID}/inputs/1/name", "Drzwi wejściowe"),
            (f"system/{SID}/inputs/1/status", str(int(status))),
        ],
    )


@pytest.mark.parametrize(
    ("line_state", "expected_zone", "expected_problem"),
    [
        (LineState.UNKNOWN, STATE_UNKNOWN, "off"),
        (LineState.CLOSED, "off", "off"),
        (LineState.OPEN, "on", "off"),
        (LineState.TAMPER, STATE_UNKNOWN, "on"),
        (LineState.FAULT, STATE_UNKNOWN, "on"),
    ],
)
async def test_zone_and_problem_state_for_every_line_state(
    hass: HomeAssistant,
    line_state: LineState,
    expected_zone: str,
    expected_problem: str,
) -> None:
    """Only CLOSED may read as "closed".

    Mapping UNKNOWN, TAMPER and FAULT onto `False` rendered a cut detector
    cable as a securely closed door. Those three states say the panel cannot
    see the line, so the zone reports `unknown` and the problem sensor - not
    the zone - carries the tamper/fault signal.
    """
    await setup_with_state(hass, zone_state(line_state))

    zone = hass.states.get(find(hass, "drzwi_wejsciowe"))
    assert zone is not None
    assert zone.state == expected_zone

    problem = hass.states.get(find(hass, "drzwi_wejsciowe_problem"))
    assert problem is not None
    assert problem.state == expected_problem


async def test_zone_problem_sensor_is_enabled_by_default(hass: HomeAssistant) -> None:
    """The problem sensor must ship enabled.

    It is now the only place a tampered or faulted zone is visible, so
    leaving it disabled in the registry by default would hide sabotage.
    """
    await setup_with_state(hass, zone_state(LineState.TAMPER))
    registry = er.async_get(hass)
    entry = registry.async_get(find(hass, "drzwi_wejsciowe_problem"))
    assert entry is not None
    assert entry.disabled_by is None
