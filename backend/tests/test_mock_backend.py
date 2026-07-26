from __future__ import annotations

import asyncio

import pytest

from cluster_monitor.config import ClusterConfig
from cluster_monitor.exceptions import JobNotFoundError
from cluster_monitor.models import BackendType, Job, JobState, Node, NodeState
from cluster_monitor.slurm import MockSlurmBackend, SlurmBackend


def _backend() -> MockSlurmBackend:
    config = ClusterConfig(
        id="local-mock",
        name="Local Mock Cluster",
        backend=BackendType.MOCK,
    )
    return MockSlurmBackend(config, delay_seconds=0)


def test_mock_backend_implements_protocol_and_is_deterministic() -> None:
    backend = _backend()

    async def read_twice() -> tuple[object, object]:
        return await backend.get_jobs(), await backend.get_jobs()

    first, second = asyncio.run(read_twice())

    assert isinstance(backend, SlurmBackend)
    assert first == second


def test_mock_data_covers_required_states_and_resources() -> None:
    backend = _backend()

    async def read_data() -> tuple[list[Node], list[Job], list[Job]]:
        return (
            await backend.get_nodes(),
            await backend.get_jobs(),
            await backend.get_recent_jobs(),
        )

    nodes, jobs, history = asyncio.run(read_data())

    assert {node.state for node in nodes} >= {
        NodeState.IDLE,
        NodeState.ALLOCATED,
        NodeState.DRAINED,
    }
    assert any(node.gpu_resources for node in nodes)
    assert any(not node.gpu_resources for node in nodes)
    assert {job.state for job in jobs} == {JobState.RUNNING, JobState.PENDING}
    assert {job.reason for job in jobs if job.state is JobState.PENDING} == {
        "Priority",
        "Resources",
    }
    assert {job.state for job in history} == {JobState.COMPLETED, JobState.FAILED}


def test_unknown_job_raises_typed_error() -> None:
    with pytest.raises(JobNotFoundError):
        asyncio.run(_backend().get_job("does-not-exist"))
