"""Tests for the immutable state model and the message reducer."""

import pytest

from custom_components.pulson_alarm import models

SID = "SID"
USER = "SID_hash"
IDX = f"system/{SID}/users/{USER}"


def test_index_list_creates_placeholders() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"{IDX}/partitions", "1,2")
    assert set(state.partitions) == {"1", "2"}
    assert state.partitions["1"].status is None


def test_leaf_updates_partition_fields() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"{IDX}/partitions", "1")
    state = models.apply_message(state, f"system/{SID}/partitions/1/status", "2")
    state = models.apply_message(state, f"system/{SID}/partitions/1/name", "Parter")
    state = models.apply_message(state, f"system/{SID}/partitions/1/ready", "1")
    state = models.apply_message(state, f"system/{SID}/partitions/1/alarm", "0")
    state = models.apply_message(state, f"system/{SID}/partitions/1/active", "true")
    partition = state.partitions["1"]
    assert partition.status == 2
    assert partition.name == "Parter"
    assert partition.ready is True
    assert partition.alarm is False
    assert partition.active is True


def test_leaf_creates_element_when_index_missing() -> None:
    state = models.apply_message(
        models.EMPTY_STATE, f"system/{SID}/inputs/7/status", "2"
    )
    assert state.zones["7"].status == 2


def test_zone_fields() -> None:
    state = models.apply_message(
        models.EMPTY_STATE, f"system/{SID}/inputs/3/block", "1"
    )
    state = models.apply_message(state, f"system/{SID}/inputs/3/block_enable", "0")
    assert state.zones["3"].blocked is True
    assert state.zones["3"].block_allowed is False


def test_output_fields() -> None:
    state = models.apply_message(
        models.EMPTY_STATE, f"system/{SID}/outputs/2/status", "1"
    )
    assert state.outputs["2"].status == 1


def test_online_and_programming_and_permissions() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"system/{SID}/online/esp", "true")
    state = models.apply_message(state, f"system/{SID}/online/simcom", "false")
    state = models.apply_message(state, f"system/{SID}/programming", "1:0")
    state = models.apply_message(state, f"{IDX}/permissions", "16367")
    assert state.modules_online == {"esp": True, "simcom": False}
    assert state.programming is True
    assert state.permissions == "16367"


def test_programming_false_when_first_segment_lacks_one() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"system/{SID}/programming", "0:1")
    assert state.programming is False


def test_unchanged_message_returns_same_object() -> None:
    state = models.apply_message(
        models.EMPTY_STATE, f"system/{SID}/partitions/1/status", "1"
    )
    same = models.apply_message(state, f"system/{SID}/partitions/1/status", "1")
    assert same is state


def test_unknown_topic_is_ignored() -> None:
    state = models.apply_message(models.EMPTY_STATE, "system/SID/mystery/thing", "x")
    assert state is models.EMPTY_STATE


def test_known_ids() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"{IDX}/inputs", "1,2,3")
    assert models.known_ids(state, "inputs") == ("1", "2", "3")
    assert models.known_ids(state, "outputs") == ()


def test_state_equality_supports_always_update_false() -> None:
    first = models.apply_message(
        models.EMPTY_STATE, f"system/{SID}/partitions/1/status", "1"
    )
    second = models.apply_message(
        models.EMPTY_STATE, f"system/{SID}/partitions/1/status", "1"
    )
    assert first == second


def test_unchanged_zone_leaf_returns_same_object() -> None:
    state = models.apply_message(
        models.EMPTY_STATE, f"system/{SID}/inputs/1/status", "1"
    )
    assert models.apply_message(state, f"system/{SID}/inputs/1/status", "1") is state


def test_unchanged_output_leaf_returns_same_object() -> None:
    state = models.apply_message(
        models.EMPTY_STATE, f"system/{SID}/outputs/1/status", "1"
    )
    assert models.apply_message(state, f"system/{SID}/outputs/1/status", "1") is state


def test_unchanged_online_returns_same_object() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"system/{SID}/online/esp", "true")
    assert models.apply_message(state, f"system/{SID}/online/esp", "true") is state


def test_unchanged_programming_returns_same_object() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"system/{SID}/programming", "1")
    assert models.apply_message(state, f"system/{SID}/programming", "1") is state


def test_unchanged_permissions_returns_same_object() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"{IDX}/permissions", "16367")
    assert models.apply_message(state, f"{IDX}/permissions", "16367") is state


def test_unchanged_index_list_returns_same_object() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"{IDX}/inputs", "1,2")
    assert models.apply_message(state, f"{IDX}/inputs", "1,2") is state


def test_outputs_index_creates_placeholders() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"{IDX}/outputs", "1,2")
    assert set(state.outputs) == {"1", "2"}
    assert models.known_ids(state, "outputs") == ("1", "2")


def test_returned_mappings_reject_mutation() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"{IDX}/partitions", "1")
    with pytest.raises(TypeError):
        state.partitions["2"] = models.PartitionData(id="2")  # type: ignore[index]


def test_unchanged_partitions_index_returns_same_object() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"{IDX}/partitions", "1")
    assert models.apply_message(state, f"{IDX}/partitions", "1") is state


def test_unchanged_outputs_index_returns_same_object() -> None:
    state = models.apply_message(models.EMPTY_STATE, f"{IDX}/outputs", "1")
    assert models.apply_message(state, f"{IDX}/outputs", "1") is state


def test_unknown_leaf_field_is_ignored() -> None:
    topic = f"system/{SID}/partitions/1/bogus"
    assert models.apply_message(models.EMPTY_STATE, topic, "x") is models.EMPTY_STATE


def test_unknown_single_segment_topic_is_ignored() -> None:
    topic = f"system/{SID}/mystery"
    assert models.apply_message(models.EMPTY_STATE, topic, "x") is models.EMPTY_STATE
