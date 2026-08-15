from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from cluster_monitor.connection import (
    ClusterConnectionError,
    RemoteCommandError,
    SshCommandResult,
)
from cluster_monitor.slurm import (
    SlurmCapabilities,
    SlurmVersionDetectionError,
    build_sacct_json_probe,
    build_sinfo_json_probe,
    build_squeue_json_probe,
    build_version_command,
    detect_slurm_capabilities,
    parse_slurm_version,
)


class FakeExecutor:
    def __init__(self, responses: dict[str, SshCommandResult | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, tuple[str, ...], str | None]] = []

    async def execute(
        self,
        remote_executable: str,
        arguments: Sequence[str] = (),
        *,
        command_type: str | None = None,
        stdin_data: bytes | None = None,
    ) -> SshCommandResult:
        assert stdin_data is None
        self.calls.append((remote_executable, tuple(arguments), command_type))
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


def _remote_error(executable: str) -> RemoteCommandError:
    return RemoteCommandError(
        "unsupported option",
        host_alias="test-hpc",
        remote_executable=executable,
        exit_code=1,
    )


def test_fixed_capability_command_builders() -> None:
    assert build_version_command().executable == "sinfo"
    assert build_version_command().arguments == ("--version",)
    assert build_sinfo_json_probe().arguments == ("--json", "--states=FUTURE")
    assert build_squeue_json_probe().executable == "squeue"
    assert build_squeue_json_probe().arguments == ("--json", "--states=COMPLETED")
    assert build_sacct_json_probe().executable == "sacct"
    assert build_sacct_json_probe().arguments == (
        "--json",
        "--allocations",
        "--starttime=now",
        "--endtime=now",
    )


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("slurm 24.05.4\n", "24.05.4"),
        ("slurm-wlm 23.11.10", "23.11.10"),
        ("22.05.8-1", "22.05.8-1"),
        ("Welcome Ubuntu 22.04.4\nslurm 24.05.4", "24.05.4"),
    ],
)
def test_parses_slurm_version(output: str, expected: str) -> None:
    assert parse_slurm_version(output) == expected


def test_rejects_unrecognized_slurm_version() -> None:
    with pytest.raises(SlurmVersionDetectionError):
        parse_slurm_version("sinfo: unknown command")


def test_detects_json_support_from_successful_valid_json() -> None:
    executor = FakeExecutor(
        {
            "slurm_version": _result("slurm 24.05.4"),
            "sinfo_json_probe": _result('{"sinfo": [], "errors": []}'),
            "squeue_json_probe": _remote_error("squeue"),
            "sacct_json_probe": _result("not-json"),
        }
    )

    capabilities = asyncio.run(detect_slurm_capabilities(executor))

    assert capabilities == SlurmCapabilities(
        version="24.05.4",
        sinfo_json=True,
        squeue_json=False,
        sacct_json=False,
    )
    assert executor.calls == [
        ("sinfo", ("--version",), "slurm_version"),
        ("sinfo", ("--json", "--states=FUTURE"), "sinfo_json_probe"),
        ("squeue", ("--json", "--states=COMPLETED"), "squeue_json_probe"),
        (
            "sacct",
            ("--json", "--allocations", "--starttime=now", "--endtime=now"),
            "sacct_json_probe",
        ),
    ]


def test_capability_detection_does_not_mask_connection_failure() -> None:
    connection_error = ClusterConnectionError(
        "offline",
        host_alias="test-hpc",
        remote_executable="sinfo",
        exit_code=255,
    )
    executor = FakeExecutor(
        {
            "slurm_version": _result("slurm 24.05.4"),
            "sinfo_json_probe": connection_error,
        }
    )

    with pytest.raises(ClusterConnectionError) as caught:
        asyncio.run(detect_slurm_capabilities(executor))

    assert caught.value is connection_error


def test_json_error_envelope_is_not_reported_as_supported() -> None:
    executor = FakeExecutor(
        {
            "slurm_version": _result("slurm 24.05.4"),
            "sinfo_json_probe": _result(
                '{"nodes": [], "errors": [{"description": "plugin unavailable"}]}'
            ),
            "squeue_json_probe": _result('{"meta": {}, "errors": []}'),
            "sacct_json_probe": _result('{"jobs": [], "errors": []}'),
        }
    )

    capabilities = asyncio.run(detect_slurm_capabilities(executor))

    assert capabilities.sinfo_json is False
    assert capabilities.squeue_json is False
    assert capabilities.sacct_json is True
