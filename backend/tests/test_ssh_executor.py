from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Any

import pytest

import cluster_monitor.connection.ssh as ssh_module
from cluster_monitor.connection import (
    ClusterConnectionError,
    OpenSshExecutor,
    RemoteCommandError,
    RemoteCommandTimeoutError,
    build_remote_command,
)
from cluster_monitor.connection.ssh import RemoteCommandOutputLimitError, logger


class MemoryStream:
    def __init__(self, value: bytes) -> None:
        self._value = value
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._value):
            return b""
        end = len(self._value) if size < 0 else min(len(self._value), self._offset + size)
        chunk = self._value[self._offset : end]
        self._offset = end
        return chunk


class RecordingStdin:
    def __init__(self, process: CompletedProcess | HangingProcess) -> None:
        self._process = process

    def write(self, value: bytes) -> None:
        self._process.stdin_data = value

    async def drain(self) -> None:
        return

    def close(self) -> None:
        return

    async def wait_closed(self) -> None:
        return


class CompletedProcess:
    def __init__(
        self,
        exit_code: int,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.returncode: int | None = exit_code
        self.stdout = MemoryStream(stdout)
        self.stderr = MemoryStream(stderr)
        self.stdin = RecordingStdin(self)
        self.stdin_data: bytes | None = None
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class HangingStream:
    def __init__(self, process: HangingProcess, chunks: list[bytes]) -> None:
        self._process = process
        self._chunks = chunks

    async def read(self, size: int = -1) -> bytes:
        if self._chunks:
            chunk = self._chunks.pop(0)
            if size >= 0 and len(chunk) > size:
                self._chunks.insert(0, chunk[size:])
                return chunk[:size]
            return chunk
        await self._process.finished.wait()
        return b""


class HangingProcess:
    def __init__(
        self,
        *,
        ignore_terminate: bool = False,
        stdout_chunks: list[bytes] | None = None,
        stderr_chunks: list[bytes] | None = None,
    ) -> None:
        self.returncode: int | None = None
        self.ignore_terminate = ignore_terminate
        self.terminated = False
        self.killed = False
        self.stdin_data: bytes | None = None
        self.communicate_started = asyncio.Event()
        self.finished = asyncio.Event()
        self.stdout = HangingStream(self, list(stdout_chunks or []))
        self.stderr = HangingStream(self, list(stderr_chunks or []))
        self.stdin = RecordingStdin(self)

    async def wait(self) -> int:
        self.communicate_started.set()
        await self.finished.wait()
        assert self.returncode is not None
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if not self.ignore_terminate:
            self.returncode = -15
            self.finished.set()

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9
        self.finished.set()


def _install_process(
    monkeypatch: pytest.MonkeyPatch,
    process: CompletedProcess | HangingProcess,
) -> tuple[list[str], dict[str, Any]]:
    captured_arguments: list[str] = []
    captured_options: dict[str, Any] = {}

    async def create_subprocess_exec(
        *arguments: str,
        **options: Any,
    ) -> CompletedProcess | HangingProcess:
        captured_arguments.extend(arguments)
        captured_options.update(options)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    return captured_arguments, captured_options


def test_builds_exact_safe_openssh_argument_array() -> None:
    executor = OpenSshExecutor(
        "sapienza-hpc",
        cluster_id="sapienza",
        ssh_executable="/usr/bin/ssh",
    )

    assert (
        build_remote_command(
            "squeue",
            ("--json", "--name", "a b", "it's"),
        )
        == """squeue --json --name 'a b' 'it'"'"'s'"""
    )
    assert executor.build_command(
        "squeue",
        ("--json", "--name", "a b", "it's"),
    ) == (
        "/usr/bin/ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "sapienza-hpc",
        """squeue --json --name 'a b' 'it'"'"'s'""",
    )


def test_metacharacters_and_newline_remain_one_quoted_remote_argument() -> None:
    executor = OpenSshExecutor("safe-hpc")
    untrusted_value = "$(touch /tmp/not-created); echo\nforged"

    remote_command = build_remote_command("squeue", ("--name", untrusted_value))
    local_arguments = executor.build_command("squeue", ("--name", untrusted_value))

    assert remote_command == "squeue --name '$(touch /tmp/not-created); echo\nforged'"
    assert shlex.split(remote_command) == ["squeue", "--name", untrusted_value]
    assert local_arguments[-1] == remote_command
    assert len(local_arguments) == 8


@pytest.mark.parametrize(
    ("host_alias", "remote_executable", "arguments"),
    [
        ("-oProxyCommand=bad", "sinfo", ()),
        ("valid-host", "", ()),
        ("valid-host", "sinfo", ("bad\x00argument",)),
    ],
)
def test_rejects_unsafe_command_components(
    host_alias: str,
    remote_executable: str,
    arguments: tuple[str, ...],
) -> None:
    if host_alias.startswith("-"):
        with pytest.raises(ValueError, match="host_alias"):
            OpenSshExecutor(host_alias)
    else:
        executor = OpenSshExecutor(host_alias)
        with pytest.raises(ValueError):
            executor.build_command(remote_executable, arguments)


def test_rejects_control_characters_in_command_type() -> None:
    executor = OpenSshExecutor("safe-hpc")

    with pytest.raises(ValueError, match="command_type"):
        asyncio.run(executor.execute("sinfo", command_type="sinfo\nforged"))


def test_executes_without_a_shell_and_logs_metadata_not_output(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_output = b"sensitive job output"
    process = CompletedProcess(0, stdout=secret_output, stderr=b"minor warning")
    arguments, options = _install_process(monkeypatch, process)
    executor = OpenSshExecutor("hpc-alias", cluster_id="research")

    with caplog.at_level(logging.INFO, logger=logger.name):
        result = asyncio.run(executor.execute("sinfo", ("--json",), command_type="sinfo"))

    assert arguments == [
        "ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "hpc-alias",
        "sinfo --json",
    ]
    assert "shell" not in options
    assert options["stdin"] is asyncio.subprocess.DEVNULL
    assert options["stdout"] is asyncio.subprocess.PIPE
    assert options["stderr"] is asyncio.subprocess.PIPE
    assert result.stdout == secret_output.decode()
    assert result.exit_code == 0
    assert "cluster_id=research" in caplog.text
    assert "command_type=sinfo" in caplog.text
    assert "sensitive job output" not in caplog.text
    record = caplog.records[-1]
    assert record.__dict__["cluster_id"] == "research"
    assert record.__dict__["exit_status"] == 0
    assert record.__dict__["timeout"] is False


def test_forwards_bounded_stdin_without_adding_it_to_the_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = CompletedProcess(0, stdout=b"42001\n")
    arguments, options = _install_process(monkeypatch, process)
    executor = OpenSshExecutor("hpc-alias")
    script = b"#!/usr/bin/env bash\nhostname\n"

    result = asyncio.run(
        executor.execute(
            "sbatch",
            ("--parsable", "--job-name=smoke"),
            command_type="sbatch_submit",
            stdin_data=script,
        )
    )

    assert options["stdin"] is asyncio.subprocess.PIPE
    assert process.stdin_data == script
    assert arguments[-1] == "sbatch --parsable --job-name=smoke"
    assert "hostname" not in arguments[-1]
    assert result.stdout == "42001\n"


def test_rejects_oversized_stdin_before_starting_ssh() -> None:
    executor = OpenSshExecutor("hpc-alias")

    with pytest.raises(ValueError, match="one MiB"):
        asyncio.run(executor.execute("sbatch", stdin_data=b"x" * 1_048_577))


def test_accepts_output_exactly_at_the_capture_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ssh_module, "MAX_CAPTURE_BYTES", 32)
    process = CompletedProcess(0, stdout=b"x" * 32, stderr=b"y" * 32)
    _install_process(monkeypatch, process)
    executor = OpenSshExecutor("hpc-alias")

    result = asyncio.run(executor.execute("sinfo"))

    assert result.stdout == "x" * 32
    assert result.stderr == "y" * 32


@pytest.mark.parametrize("overflow_stream", ["stdout", "stderr"])
def test_output_overflow_terminates_and_drains_without_exposing_payload(
    overflow_stream: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(ssh_module, "MAX_CAPTURE_BYTES", 32)
    private_payload = b"private-output-that-must-never-be-exposed"
    process = HangingProcess(
        stdout_chunks=[private_payload] if overflow_stream == "stdout" else None,
        stderr_chunks=[private_payload] if overflow_stream == "stderr" else None,
    )
    _install_process(monkeypatch, process)
    executor = OpenSshExecutor("hpc-alias", cluster_id="bounded-cluster")

    with (
        caplog.at_level(logging.WARNING, logger=logger.name),
        pytest.raises(RemoteCommandOutputLimitError) as caught,
    ):
        asyncio.run(executor.execute("squeue", command_type="squeue_jobs"))

    assert process.terminated
    assert not process.killed
    assert process.returncode == -15
    assert caught.value.stream_name == overflow_stream
    assert caught.value.limit_bytes == 32
    assert caught.value.exit_code == -15
    assert caught.value.stdout == ""
    assert caught.value.stderr == ""
    assert "private-output" not in str(caught.value)
    assert "private-output" not in caplog.text
    assert "ssh_command_output_limit" in caplog.text
    assert f"output_stream={overflow_stream}" in caplog.text
    assert "output_limit_bytes=32" in caplog.text


def test_output_overflow_kills_when_ssh_ignores_termination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ssh_module, "MAX_CAPTURE_BYTES", 16)
    process = HangingProcess(
        ignore_terminate=True,
        stdout_chunks=[b"x" * 17],
    )
    _install_process(monkeypatch, process)
    executor = OpenSshExecutor(
        "hpc-alias",
        terminate_grace_seconds=0.005,
    )

    with pytest.raises(RemoteCommandOutputLimitError):
        asyncio.run(executor.execute("sacct"))

    assert process.terminated
    assert process.killed
    assert process.returncode == -9


def test_nonzero_remote_status_raises_remote_command_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = CompletedProcess(2, stdout=b"partial", stderr=b"invalid option")
    _install_process(monkeypatch, process)
    executor = OpenSshExecutor("hpc-alias")

    with pytest.raises(RemoteCommandError) as caught:
        asyncio.run(executor.execute("squeue", ("--bad-option",)))

    assert caught.value.exit_code == 2
    assert caught.value.stdout == "partial"
    assert caught.value.stderr == "invalid option"
    assert caught.value.host_alias == "hpc-alias"


def test_ssh_exit_255_is_a_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = CompletedProcess(255, stderr=b"Connection refused")
    _install_process(monkeypatch, process)
    executor = OpenSshExecutor("offline-hpc")

    with pytest.raises(ClusterConnectionError) as caught:
        asyncio.run(executor.execute("sinfo", ("--version",)))

    assert caught.value.exit_code == 255
    assert caught.value.stderr == "Connection refused"
    assert not isinstance(caught.value, RemoteCommandError)


def test_local_ssh_start_failure_is_a_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_to_start(*arguments: str, **options: Any) -> None:
        del arguments, options
        raise FileNotFoundError("ssh")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_to_start)
    executor = OpenSshExecutor("offline-hpc")

    with pytest.raises(ClusterConnectionError) as caught:
        asyncio.run(executor.execute("sinfo"))

    assert caught.value.exit_code is None
    assert "FileNotFoundError" not in str(caught.value)


def test_timeout_terminates_then_kills_and_drains_process(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    process = HangingProcess(ignore_terminate=True)
    _install_process(monkeypatch, process)
    executor = OpenSshExecutor(
        "slow-hpc",
        cluster_id="slow-cluster",
        timeout_seconds=0.005,
        terminate_grace_seconds=0.005,
    )

    with (
        caplog.at_level(logging.WARNING, logger=logger.name),
        pytest.raises(RemoteCommandTimeoutError) as caught,
    ):
        asyncio.run(executor.execute("sacct", ("--json",), command_type="sacct"))

    assert caught.value.timeout_seconds == 0.005
    assert process.terminated
    assert process.killed
    assert process.returncode == -9
    assert "cluster_id=slow-cluster" in caplog.text
    assert "timeout=true" in caplog.text
    assert "exit_status=-9" in caplog.text


def test_cancellation_terminates_process_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = HangingProcess()
    _install_process(monkeypatch, process)
    executor = OpenSshExecutor("cancel-hpc")

    async def cancel_execution() -> None:
        task = asyncio.create_task(executor.execute("sinfo", ("--json",)))
        await process.communicate_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_execution())

    assert process.terminated
    assert not process.killed
    assert process.returncode == -15
