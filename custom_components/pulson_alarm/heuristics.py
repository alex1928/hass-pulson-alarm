"""Guess a zone device class from the name the installer gave it."""

from __future__ import annotations

from typing import Final
import unicodedata

from homeassistant.components.binary_sensor import BinarySensorDeviceClass

# Order matters: the first matching group wins.
_RULES: Final[tuple[tuple[tuple[str, ...], BinarySensorDeviceClass], ...]] = (
    (("dym", "smoke", "pozar", "fire"), BinarySensorDeviceClass.SMOKE),
    (("zalanie", "woda", "flood", "water", "leak"), BinarySensorDeviceClass.MOISTURE),
    (("czad", "tlenek", "carbon"), BinarySensorDeviceClass.CO),
    (("gaz", "gas"), BinarySensorDeviceClass.GAS),
    (("okno", "window"), BinarySensorDeviceClass.WINDOW),
    (
        ("drzwi", "door", "brama", "gate", "wejscie", "entry"),
        BinarySensorDeviceClass.DOOR,
    ),
    (("ruch", "pir", "motion"), BinarySensorDeviceClass.MOTION),
)

DEFAULT_DEVICE_CLASS: Final = BinarySensorDeviceClass.MOTION


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def guess_device_class(name: str | None) -> BinarySensorDeviceClass:
    """Return the best guess for a zone, defaulting to motion."""
    if not name:
        return DEFAULT_DEVICE_CLASS
    haystack = _normalise(name)
    for needles, device_class in _RULES:
        if any(needle in haystack for needle in needles):
            return device_class
    return DEFAULT_DEVICE_CLASS
