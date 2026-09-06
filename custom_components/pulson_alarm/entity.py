"""Shared entity base."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import PulsonConfigEntry, PulsonCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


class PulsonEntity(CoordinatorEntity[PulsonCoordinator]):
    """Base entity for everything belonging to one panel."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PulsonCoordinator) -> None:
        """Attach to the panel device."""
        super().__init__(coordinator)
        system_id = coordinator.config_entry.data["system_id"]
        self._system_id = system_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, system_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name="PulsON Alarm",
        )


@callback
def async_add_new(  # noqa: PLR0917 - six related, order-significant params
    coordinator: PulsonCoordinator,
    entry: PulsonConfigEntry,
    known: set[str],
    ids: Callable[[], Iterable[str]],
    build: Callable[[str], Iterable[PulsonEntity]],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add entities for elements the panel reported for the first time."""

    @callback
    def _sync() -> None:
        new: list[PulsonEntity] = []
        for element_id in ids():
            if element_id in known:
                continue
            known.add(element_id)
            new.extend(build(element_id))
        if new:
            async_add_entities(new)

    entry.async_on_unload(coordinator.async_add_listener(_sync))
    _sync()
