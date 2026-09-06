"""Tests for the zone device-class heuristic."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
import pytest

from custom_components.pulson_alarm.heuristics import guess_device_class


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Drzwi wejściowe", BinarySensorDeviceClass.DOOR),
        ("wejście", BinarySensorDeviceClass.DOOR),
        ("Front Door", BinarySensorDeviceClass.DOOR),
        ("Okno salon", BinarySensorDeviceClass.WINDOW),
        ("Ruch w kuchni", BinarySensorDeviceClass.MOTION),
        ("PIR garaż", BinarySensorDeviceClass.MOTION),
        ("Czujnik dymu", BinarySensorDeviceClass.SMOKE),
        ("Zalanie pralnia", BinarySensorDeviceClass.MOISTURE),
        ("Czujnik gazu", BinarySensorDeviceClass.GAS),
        ("Czad kotłownia", BinarySensorDeviceClass.CO),
        ("salon", BinarySensorDeviceClass.MOTION),
        (None, BinarySensorDeviceClass.MOTION),
    ],
)
def test_guess_device_class(
    name: str | None, expected: BinarySensorDeviceClass
) -> None:
    assert guess_device_class(name) is expected
