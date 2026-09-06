"""Tests for the pure protocol layer."""

import pytest

from custom_components.pulson_alarm import protocol


def test_mqtt_username_matches_reference_vector() -> None:
    # Verified against a live panel: this exact username was accepted by the broker.
    assert protocol.mqtt_username("0011223344556677889900aa", "1111") == (
        "0011223344556677889900aa_88c4a919703e9f665f051984495536c4"
    )


def test_mqtt_password_matches_reference_vector() -> None:
    assert protocol.mqtt_password("0011223344556677889900aa", "1111") == (
        "3b2fb28cd386842aac0ebce28c4a1559"
    )


def test_mqtt_username_and_password_differ() -> None:
    user = protocol.mqtt_username("sid", "1234")
    password = protocol.mqtt_password("sid", "1234")
    assert user.startswith("sid_")
    assert len(password) == 32
    assert password != user.split("_", 1)[1]


def test_username_changes_with_pin() -> None:
    assert protocol.mqtt_username("sid", "1111") != protocol.mqtt_username(
        "sid", "2222"
    )


def test_topic_builders() -> None:
    assert protocol.topic_index("SID", "USER", "partitions") == (
        "system/SID/users/USER/partitions"
    )
    assert protocol.topic_leaf("SID", "inputs", "3", "status") == (
        "system/SID/inputs/3/status"
    )
    assert protocol.topic_command("SID", "panic_alarm") == "system/SID/panic_alarm"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("false", False),
        ("0", False),
        ("nonsense", False),
        (None, None),
    ],
)
def test_parse_bool(raw: str | None, expected: bool | None) -> None:
    assert protocol.parse_bool(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5", 5), ("-2", -2), ("", None), ("abc", None), (None, None)],
)
def test_parse_int(raw: str | None, expected: int | None) -> None:
    assert protocol.parse_int(raw) == expected


def test_parse_qr_valid() -> None:
    result = protocol.parse_qr("1;solid.pulsonalarm.pl;8883;4321;00112233")
    assert result is not None
    assert result.host == "solid.pulsonalarm.pl"
    assert result.port == 8883
    assert result.pin == "4321"
    assert result.system_id == "00112233"


def test_parse_qr_tolerates_whitespace() -> None:
    result = protocol.parse_qr("  1; host ; 8883 ; 1234 ; abc  ")
    assert result is not None
    assert result.host == "host"
    assert result.system_id == "abc"


@pytest.mark.parametrize("raw", ["", "1;host;8883", "garbage", "1;host;notaport;p;s"])
def test_parse_qr_invalid(raw: str) -> None:
    assert protocol.parse_qr(raw) is None


def test_alarm_states_contains_intruder_not_disarmed() -> None:
    assert protocol.PartitionState.ALARM_INTRUDER in protocol.ALARM_STATES
    assert protocol.PartitionState.DISARMED not in protocol.ALARM_STATES
    assert protocol.PartitionState.EXIT_TIME not in protocol.ALARM_STATES


def test_fields_cover_every_module() -> None:
    assert set(protocol.FIELDS) == set(protocol.MODULES)
    assert "status" in protocol.FIELDS[protocol.MODULE_PARTITIONS]
    assert "block_enable" in protocol.FIELDS[protocol.MODULE_INPUTS]
