from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from cluster_monitor.config import ClusterConfig
from cluster_monitor.connection import (
    ClusterConnectionError,
    RemoteCommandError,
    RemoteCommandOutputLimitError,
    RemoteCommandTimeoutError,
    SshCommandResult,
)
from cluster_monitor.exceptions import (
    JobActionRejectedError,
    JobActionScopeUnsupportedError,
    JobActionsDisabledError,
    JobActionUncertainError,
)
from cluster_monitor.models import (
    BackendType,
    ConnectionStatus,
    JobSubmissionRequest,
    NodeState,
)
from cluster_monitor.slurm.ssh_backend import SshSlurmBackend

FIXTURES = Path(__file__).parent / "fixtures"


class FakeExecutor:
    def __init__(self, responses: dict[str, SshCommandResult | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, tuple[str, ...], str | None]] = []
        self.stdin_calls: list[tuple[str | None, bytes | None]] = []

    async def execute(
        self,
        remote_executable: str,
        arguments: Sequence[str] = (),
        *,
        command_type: str | None = None,
        stdin_data: bytes | None = None,
    ) -> SshCommandResult:
        self.calls.append((remote_executable, tuple(arguments), command_type))
        self.stdin_calls.append((command_type, stdin_data))
        response = self.responses[command_type or remote_executable]
        if isinstance(response, Exception):
            raise response
        return response


def _result(stdout: str) -> SshCommandResult:
    return SshCommandResult(
        stdout=stdout,
        stderr="",
        exit_code=0,
        duration_seconds=0.01,
    )


def _fixture(relative_path: str) -> str:
    return (FIXTURES / relative_path).read_text(encoding="utf-8")


def _config() -> ClusterConfig:
    return ClusterConfig(
        id="real-test",
        name="Real Test Cluster",
        backend=BackendType.SSH,
        ssh_host="test-hpc",
        allow_job_actions=True,
    )


def _json_executor() -> FakeExecutor:
    sinfo = _fixture("json/sinfo_24_11.json")
    return FakeExecutor(
        {
            "slurm_version": _result("slurm 24.11.1"),
            "sinfo_json_probe": _result('{"sinfo": [], "errors": []}'),
            "squeue_json_probe": _result('{"jobs": [], "errors": []}'),
            "sacct_json_probe": _result('{"jobs": [], "errors": []}'),
            "remote_user": _result("researcher\n"),
            "sinfo_partitions_json": _result(sinfo),
            "sinfo_nodes_json": _result(sinfo),
            "squeue_jobs_json": _result(_fixture("json/squeue_24_11.json")),
            "sacct_jobs_json": _result(_fixture("json/sacct_24_11.json")),
            "sacct_job_json": _result(_fixture("json/sacct_24_11.json")),
        }
    )


def test_live_backend_normalizes_all_read_operations() -> None:
    executor = _json_executor()
    backend = SshSlurmBackend(_config(), executor=executor, cache_ttl_seconds=30)

    async def exercise() -> None:
        cluster = await backend.get_cluster()
        partitions = await backend.get_partitions()
        nodes = await backend.get_nodes()
        jobs = await backend.get_jobs()
        history = await backend.get_recent_jobs(limit=1)
        details = await backend.get_job("11998")
        overview = await backend.get_overview()

        assert cluster.connection_status is ConnectionStatus.CONNECTED
        assert cluster.slurm_version == "24.11.1"
        assert {partition.name for partition in partitions} == {"compute", "gpu"}
        assert {node.state for node in nodes} >= {NodeState.IDLE, NodeState.MIXED}
        assert {job.user for job in jobs} == {"researcher"}
        assert len(history) == 1
        assert details.job_id == "11998"
        assert details.accounting is not None
        assert overview.total_nodes == len(nodes)
        assert overview.running_jobs == 1
        assert overview.pending_jobs == 1

    asyncio.run(exercise())
    assert sum(call[2] == "remote_user" for call in executor.calls) == 1
    assert sum(call[2] == "sinfo_nodes_json" for call in executor.calls) == 1
    assert sum(call[2] == "squeue_jobs_json" for call in executor.calls) == 1


def test_invalid_json_falls_back_to_fixed_partition_format() -> None:
    executor = _json_executor()
    executor.responses["sinfo_partitions_json"] = _result("not-json")
    executor.responses["sinfo_partitions_text"] = _result(_fixture("text/partitions.txt"))
    backend = SshSlurmBackend(_config(), executor=executor)

    partitions = asyncio.run(backend.get_partitions())

    assert {partition.name for partition in partitions} == {"compute", "gpu", "long"}
    assert [call[2] for call in executor.calls][-2:] == [
        "sinfo_partitions_json",
        "sinfo_partitions_text",
    ]


def test_cluster_connection_error_is_sanitized_into_metadata() -> None:
    error = ClusterConnectionError(
        "private transport detail",
        host_alias="test-hpc",
        remote_executable="sinfo",
        stderr="private banner",
        exit_code=255,
    )
    executor = FakeExecutor({"slurm_version": error})
    backend = SshSlurmBackend(_config(), executor=executor)

    cluster = asyncio.run(backend.get_cluster())

    assert cluster.connection_status is ConnectionStatus.UNAVAILABLE
    assert cluster.last_error is not None
    assert "VPN" in cluster.last_error
    assert "private" not in cluster.last_error
    assert "test-hpc" not in cluster.last_error


def test_submit_job_sends_only_the_script_over_stdin() -> None:
    executor = _json_executor()
    executor.responses["sbatch_submit"] = _result("42001;test-cluster\n")
    backend = SshSlurmBackend(_config(), executor=executor)
    request = JobSubmissionRequest(
        job_name="smoke-test",
        script="#!/usr/bin/env bash\nhostname\n",
        partition="compute",
        nodes=1,
        cpus_per_task=2,
        memory_mb=2048,
        time_limit_minutes=5,
        gpus_per_node=0,
    )

    receipt = asyncio.run(backend.submit_job(request))

    assert receipt.job_id == "42001"
    submit_call = next(call for call in executor.calls if call[2] == "sbatch_submit")
    assert submit_call[0] == "/usr/bin/env"
    assert submit_call[1][:11] == (
        "-u",
        "BASH_ENV",
        "-u",
        "ENV",
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-p",
        "-c",
        'for name in "${!SBATCH_@}"; do unset "$name"; done; '
        'unset SLURM_CLUSTERS; exec sbatch "$@"',
        "cluster-monitor-sbatch",
    )
    assert all("hostname" not in argument for argument in submit_call[1])
    assert ("sbatch_submit", request.script.encode()) in executor.stdin_calls


def test_job_actions_require_per_cluster_opt_in() -> None:
    executor = _json_executor()
    disabled_config = _config().model_copy(update={"allow_job_actions": False})
    backend = SshSlurmBackend(disabled_config, executor=executor)
    request = JobSubmissionRequest(
        job_name="test",
        script="#!/usr/bin/env bash\ntrue\n",
    )

    with pytest.raises(JobActionsDisabledError):
        asyncio.run(backend.submit_job(request))

    assert executor.calls == []


def test_submit_job_rejection_and_unknown_receipt_are_distinct() -> None:
    rejected_executor = _json_executor()
    rejected_executor.responses["sbatch_submit"] = RemoteCommandError(
        "scheduler detail",
        host_alias="test-hpc",
        remote_executable="sbatch",
        exit_code=1,
        stderr="private policy text",
    )
    rejected_backend = SshSlurmBackend(_config(), executor=rejected_executor)
    request = JobSubmissionRequest(
        job_name="test",
        script="#!/usr/bin/env bash\ntrue\n",
    )

    with pytest.raises(JobActionRejectedError, match="Slurm rejected"):
        asyncio.run(rejected_backend.submit_job(request))

    uncertain_executor = _json_executor()
    uncertain_executor.responses["sbatch_submit"] = _result("unexpected response")
    uncertain_backend = SshSlurmBackend(_config(), executor=uncertain_executor)
    with pytest.raises(JobActionUncertainError, match="may still have been created"):
        asyncio.run(uncertain_backend.submit_job(request))


def test_submit_timeout_warns_that_outcome_is_uncertain() -> None:
    executor = _json_executor()
    executor.responses["sbatch_submit"] = RemoteCommandTimeoutError(
        "timed out",
        host_alias="test-hpc",
        remote_executable="sbatch",
        timeout_seconds=15,
    )
    backend = SshSlurmBackend(_config(), executor=executor)
    request = JobSubmissionRequest(
        job_name="test",
        script="#!/usr/bin/env bash\ntrue\n",
    )

    with pytest.raises(JobActionUncertainError, match="Refresh Jobs"):
        asyncio.run(backend.submit_job(request))


def test_submit_output_overflow_warns_that_outcome_is_uncertain() -> None:
    executor = _json_executor()
    executor.responses["sbatch_submit"] = RemoteCommandOutputLimitError(
        host_alias="test-hpc",
        remote_executable="sbatch",
        exit_code=None,
        stream_name="stdout",
        limit_bytes=8 * 1_048_576,
    )
    backend = SshSlurmBackend(_config(), executor=executor)
    request = JobSubmissionRequest(
        job_name="test",
        script="#!/usr/bin/env bash\ntrue\n",
    )

    with pytest.raises(JobActionUncertainError, match="Refresh Jobs"):
        asyncio.run(backend.submit_job(request))


def test_cancel_job_checks_state_then_invokes_one_job_id() -> None:
    executor = _json_executor()
    executor.responses["scancel_job"] = _result("")
    backend = SshSlurmBackend(_config(), executor=executor)

    receipt = asyncio.run(backend.cancel_job("12002"))

    assert receipt.job_id == "12002"
    cancel_call = next(call for call in executor.calls if call[2] == "scancel_job")
    assert cancel_call == ("scancel", ("--quiet", "12002"), "scancel_job")


def test_cancel_output_overflow_warns_that_outcome_is_uncertain() -> None:
    executor = _json_executor()
    executor.responses["scancel_job"] = RemoteCommandOutputLimitError(
        host_alias="test-hpc",
        remote_executable="scancel",
        exit_code=None,
        stream_name="stderr",
        limit_bytes=8 * 1_048_576,
    )
    backend = SshSlurmBackend(_config(), executor=executor)

    with pytest.raises(JobActionUncertainError, match="Refresh the job"):
        asyncio.run(backend.cancel_job("12002"))


def test_cancel_terminal_job_is_rejected_without_scancel() -> None:
    executor = _json_executor()
    backend = SshSlurmBackend(_config(), executor=executor)

    with pytest.raises(JobActionRejectedError, match="already have finished"):
        asyncio.run(backend.cancel_job("11998"))

    assert all(call[2] != "scancel_job" for call in executor.calls)


@pytest.mark.parametrize(
    ("job_id", "scope"),
    [
        ("42000", "array"),
        ("43000", "heterogeneous"),
    ],
)
def test_cancel_rejects_multi_job_scope_even_for_numeric_id(
    job_id: str,
    scope: str,
) -> None:
    executor = _json_executor()
    executor.responses["sacct_job_json"] = _result(_fixture("json/sacct_scoped_jobs_24_11.json"))
    backend = SshSlurmBackend(_config(), executor=executor)

    with pytest.raises(JobActionScopeUnsupportedError) as caught:
        asyncio.run(backend.cancel_job(job_id))

    assert caught.value.details == {"job_id": job_id, "scope": scope}
    assert all(call[2] != "scancel_job" for call in executor.calls)
