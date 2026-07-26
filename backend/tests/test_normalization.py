from __future__ import annotations

import pytest

from cluster_monitor.models import JobState, NodeState
from cluster_monitor.slurm import normalize_job_state, normalize_node_state


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PENDING", JobState.PENDING),
        ("CONFIGURING", JobState.PENDING),
        ("RUNNING+", JobState.RUNNING),
        ("COMPLETING", JobState.RUNNING),
        ("RESIZING", JobState.RUNNING),
        ("COMPLETED", JobState.COMPLETED),
        ("FAILED", JobState.FAILED),
        ("NODE_FAIL", JobState.FAILED),
        ("CANCELLED by 1000", JobState.CANCELLED),
        ("TIMEOUT", JobState.TIMEOUT),
        ("OUT_OF_MEMORY", JobState.OUT_OF_MEMORY),
        ("SUSPENDED", JobState.SUSPENDED),
        ("future_state", JobState.UNKNOWN),
        (None, JobState.UNKNOWN),
    ],
)
def test_normalizes_job_states(raw: str | None, expected: JobState) -> None:
    assert normalize_job_state(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("IDLE", NodeState.IDLE),
        ("IDLE*", NodeState.DOWN),
        ("IDLE~", NodeState.DOWN),
        ("IDLE#", NodeState.DOWN),
        ("IDLE!", NodeState.DOWN),
        ("IDLE%", NodeState.DOWN),
        ("IDLE$", NodeState.DRAINED),
        ("IDLE@", NodeState.DOWN),
        ("IDLE^", NodeState.DOWN),
        ("IDLE-", NodeState.UNKNOWN),
        ("IDLE+PLANNED", NodeState.UNKNOWN),
        ("IDLE+MAINT", NodeState.DRAINED),
        ("ALLOCATED", NodeState.ALLOCATED),
        ("ALLOCATED+", NodeState.ALLOCATED),
        ("ALLOCATED*", NodeState.DOWN),
        ("ALLOCATED$", NodeState.DRAINED),
        ("MIXED", NodeState.MIXED),
        ("MIXED~", NodeState.DOWN),
        ("ALLOCATED+DRAIN", NodeState.DRAINED),
        ("DRAINING", NodeState.DRAINED),
        ("DRNG", NodeState.DRAINED),
        ("FAILG", NodeState.DRAINED),
        ("DOWN+NO_RESPOND", NodeState.DOWN),
        ("COMPLETING", NodeState.COMPLETING),
        ("COMPLETING@", NodeState.DOWN),
        ("future_state", NodeState.UNKNOWN),
        (None, NodeState.UNKNOWN),
    ],
)
def test_normalizes_node_states(raw: str | None, expected: NodeState) -> None:
    assert normalize_node_state(raw) is expected
