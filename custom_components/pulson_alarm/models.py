"""Immutable state model and the pure message reducer."""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

from .protocol import (
    MODULE_INPUTS,
    MODULE_OUTPUTS,
    MODULE_PARTITIONS,
    parse_bool,
    parse_int,
)

_LEAF_SEGMENTS: Final = 3
_ONLINE_SEGMENTS: Final = 2


@dataclass(frozen=True, slots=True)
class PartitionData:
    """One alarm partition."""

    id: str
    name: str | None = None
    status: int | None = None
    alarm: bool | None = None
    ready: bool | None = None
    exit_time: int | None = None
    active: bool | None = None
    night_mode: bool | None = None


@dataclass(frozen=True, slots=True)
class ZoneData:
    """One detection zone (input line)."""

    id: str
    name: str | None = None
    status: int | None = None
    blocked: bool | None = None
    block_allowed: bool | None = None


@dataclass(frozen=True, slots=True)
class OutputData:
    """One programmable (PGM) output."""

    id: str
    name: str | None = None
    status: int | None = None


@dataclass(frozen=True, slots=True)
class PulsonState:
    """Everything the panel has told us so far."""

    partitions: Mapping[str, PartitionData]
    zones: Mapping[str, ZoneData]
    outputs: Mapping[str, OutputData]
    modules_online: Mapping[str, bool]
    programming: bool | None = None
    permissions: str | None = None


EMPTY_STATE: Final = PulsonState(
    partitions=MappingProxyType({}),
    zones=MappingProxyType({}),
    outputs=MappingProxyType({}),
    modules_online=MappingProxyType({}),
)

_PARTITION_FIELDS: Final[dict[str, str]] = {
    "name": "name",
    "status": "status",
    "alarm": "alarm",
    "ready": "ready",
    "exit_time": "exit_time",
    "active": "active",
    "night_mode": "night_mode",
}
_ZONE_FIELDS: Final[dict[str, str]] = {
    "name": "name",
    "status": "status",
    "block": "blocked",
    "block_enable": "block_allowed",
}
_OUTPUT_FIELDS: Final[dict[str, str]] = {"name": "name", "status": "status"}

_BOOL_FIELDS: Final = frozenset(
    {"alarm", "ready", "active", "night_mode", "blocked", "block_allowed"}
)
_INT_FIELDS: Final = frozenset({"status", "exit_time"})


def _coerce(attribute: str, payload: str) -> bool | int | str | None:
    if attribute in _BOOL_FIELDS:
        return parse_bool(payload)
    if attribute in _INT_FIELDS:
        return parse_int(payload)
    return payload


def _strip_prefix(topic: str) -> list[str]:
    """Return the meaningful topic tail, dropping system/{sid} and users/{user}."""
    parts = topic.split("/")
    if "users" in parts:
        return parts[parts.index("users") + 2 :]
    return parts[2:]


def _apply_index(state: PulsonState, module: str, payload: str) -> PulsonState:
    ids = [item.strip() for item in payload.split(",") if item.strip()]
    if module == MODULE_PARTITIONS:
        current = dict(state.partitions)
        added = {i: PartitionData(id=i) for i in ids if i not in current}
        if not added:
            return state
        return replace(state, partitions=MappingProxyType(current | added))
    if module == MODULE_INPUTS:
        zones = dict(state.zones)
        new_zones = {i: ZoneData(id=i) for i in ids if i not in zones}
        if not new_zones:
            return state
        return replace(state, zones=MappingProxyType(zones | new_zones))
    outputs = dict(state.outputs)
    new_outputs = {i: OutputData(id=i) for i in ids if i not in outputs}
    if not new_outputs:
        return state
    return replace(state, outputs=MappingProxyType(outputs | new_outputs))


def _update_partition(
    state: PulsonState, element_id: str, attribute: str, payload: str
) -> PulsonState:
    """Update a partition field, returning unchanged state if no change."""
    existing = state.partitions.get(element_id) or PartitionData(id=element_id)
    updated = replace(existing, **{attribute: _coerce(attribute, payload)})  # type: ignore[arg-type]
    if updated == existing and element_id in state.partitions:
        return state
    return replace(
        state,
        partitions=MappingProxyType(dict(state.partitions) | {element_id: updated}),
    )


def _update_zone(
    state: PulsonState, element_id: str, attribute: str, payload: str
) -> PulsonState:
    """Update a zone field, returning unchanged state if no change."""
    zone = state.zones.get(element_id) or ZoneData(id=element_id)
    new_zone = replace(zone, **{attribute: _coerce(attribute, payload)})  # type: ignore[arg-type]
    if new_zone == zone and element_id in state.zones:
        return state
    return replace(
        state, zones=MappingProxyType(dict(state.zones) | {element_id: new_zone})
    )


def _update_output(
    state: PulsonState, element_id: str, attribute: str, payload: str
) -> PulsonState:
    """Update an output field, returning unchanged state if no change."""
    output = state.outputs.get(element_id) or OutputData(id=element_id)
    new_output = replace(output, **{attribute: _coerce(attribute, payload)})  # type: ignore[arg-type]
    if new_output == output and element_id in state.outputs:
        return state
    return replace(
        state, outputs=MappingProxyType(dict(state.outputs) | {element_id: new_output})
    )


def _apply_leaf(
    state: PulsonState, module: str, element_id: str, field: str, payload: str
) -> PulsonState:
    """Apply a leaf field update to the appropriate module's element."""
    field_map = {
        MODULE_PARTITIONS: _PARTITION_FIELDS,
        MODULE_INPUTS: _ZONE_FIELDS,
        MODULE_OUTPUTS: _OUTPUT_FIELDS,
    }.get(module)

    if field_map is None:
        return state

    attribute = field_map.get(field)
    if attribute is None:
        return state

    updaters = {
        MODULE_PARTITIONS: _update_partition,
        MODULE_INPUTS: _update_zone,
        MODULE_OUTPUTS: _update_output,
    }

    updater = updaters.get(module)
    return updater(state, element_id, attribute, payload) if updater else state


def apply_message(state: PulsonState, topic: str, payload: str) -> PulsonState:  # noqa: PLR0911
    """Fold one MQTT message into the state. Returns the same object if unchanged."""
    segments = _strip_prefix(topic)
    if not segments:
        return state

    head = segments[0]
    segment_count = len(segments)

    # Handle module online status
    if head == "online" and segment_count == _ONLINE_SEGMENTS:
        value = parse_bool(payload)
        if value is None or state.modules_online.get(segments[1]) == value:
            return state
        new_modules_online = dict(state.modules_online) | {segments[1]: value}
        return replace(state, modules_online=MappingProxyType(new_modules_online))

    # Handle programming status
    if head == "programming":
        value = "1" in payload.split(":", maxsplit=1)[0]
        return (
            state if state.programming == value else replace(state, programming=value)
        )

    # Handle single-segment topics
    if segment_count == 1:
        if head == "permissions":
            return (
                state
                if state.permissions == payload
                else replace(state, permissions=payload)
            )
        if head in (MODULE_PARTITIONS, MODULE_INPUTS, MODULE_OUTPUTS):
            return _apply_index(state, head, payload)
        return state

    # Handle leaf topics
    if segment_count >= _LEAF_SEGMENTS and head in (
        MODULE_PARTITIONS,
        MODULE_INPUTS,
        MODULE_OUTPUTS,
    ):
        return _apply_leaf(state, head, segments[1], segments[2], payload)
    return state


def known_ids(state: PulsonState, module: str) -> tuple[str, ...]:
    """Return the element ids known for a module, in numeric-then-lexical order."""
    source: Mapping[str, object] = {
        MODULE_PARTITIONS: state.partitions,
        MODULE_INPUTS: state.zones,
        MODULE_OUTPUTS: state.outputs,
    }.get(module, {})
    return tuple(
        sorted(source, key=lambda i: (not i.isdigit(), int(i) if i.isdigit() else 0, i))
    )
