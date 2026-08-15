"""Asynchronous command execution through the local OpenSSH client."""

from __future__ import annotations

import asyncio
import re
import shlex
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cluster_monitor.connection.exceptions import (
    ClusterConnectionError,
    RemoteCommandError,
    RemoteCommandTimeoutError,
)
from cluster_monitor.logging import get_logger

logger = get_logger("ssh")

_HOST_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_LOG_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_SSH_CONNECTION_ERROR = 255
_MAX_STDIN_BYTES = 1_048_576
# Maximum retained bytes for each of stdout and stderr.
MAX_CAPTURE_BYTES = 8 * 1_048_576
_STREAM_READ_BYTES = 64 * 1024
_MAX_STREAM_DIAGNOSTIC_BYTES = 64 * 1024

_StreamName = Literal["stdout", "stderr"]


@dataclass(frozen=True, slots=True)
class SshCommandResult:
    """Captured result of a successful remote command."""

    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float


class SshByteStream:
    """A bounded-diagnostic byte stream backed by one OpenSSH process."""

    def __init__(
        self,
        process: asyncio.subprocess.Process,
        *,
        host_alias: str,
        remote_executable: str,
        stderr_task: asyncio.Task[bytes],
    ) -> None:
        if process.stdout is None:
            raise RuntimeError("OpenSSH process did not expose a stdout pipe")
        self._process = process
        self._stdout = process.stdout
        self._host_alias = host_alias
        self._remote_executable = remote_executable
        self._stderr_task = stderr_task
        self._finished = False

    def __aiter__(self) -> SshByteStream:
        return self

    async def __anext__(self) -> bytes:
        chunk = await self._stdout.read(_STREAM_READ_BYTES)
        if chunk:
            return chunk
        if self._finished:
            raise StopAsyncIteration
        self._finished = True
        exit_code = await self._process.wait()
        stderr = _decode(await self._stderr_task)
        if exit_code == _SSH_CONNECTION_ERROR:
            raise ClusterConnectionError(
                "OpenSSH lost the configured cluster connection.",
                host_alias=self._host_alias,
                remote_executable=self._remote_executable,
                exit_code=exit_code,
                stderr=stderr,
            )
        if exit_code != 0:
            raise RemoteCommandError(
                "The remote streaming command returned a non-zero exit status.",
                host_alias=self._host_alias,
                remote_executable=self._remote_executable,
                exit_code=exit_code,
                stderr=stderr,
            )
        raise StopAsyncIteration


class RemoteCommandOutputLimitError(RemoteCommandError):
    """A remote command exceeded the bounded output capture limit.

    Captured bytes are deliberately discarded from this exception so callers
    can report the failure without accidentally exposing command output.
    """

    def __init__(
        self,
        *,
        host_alias: str,
        remote_executable: str,
        exit_code: int | None,
        stream_name: str,
        limit_bytes: int,
    ) -> None:
        super().__init__(
            "The remote command exceeded the configured output capture limit.",
            host_alias=host_alias,
            remote_executable=remote_executable,
            exit_code=exit_code,
        )
        self.stream_name = stream_name
        self.limit_bytes = limit_bytes


class _OutputLimitExceeded(Exception):
    def __init__(self, stream_names: set[_StreamName]) -> None:
        super().__init__("bounded subprocess output exceeded")
        self.stream_name = ",".join(sorted(stream_names))


class OpenSshExecutor:
    """Execute fixed remote programs through OpenSSH without a local shell."""

    def __init__(
        self,
        host_alias: str,
        *,
        timeout_seconds: float = 15.0,
        ssh_executable: str | Path = "ssh",
        terminate_grace_seconds: float = 1.0,
        cluster_id: str | None = None,
    ) -> None:
        if not _HOST_ALIAS.fullmatch(host_alias):
            raise ValueError("host_alias must be a valid OpenSSH alias without whitespace")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if terminate_grace_seconds <= 0:
            raise ValueError("terminate_grace_seconds must be greater than zero")

        executable = str(ssh_executable)
        if not executable or "\x00" in executable:
            raise ValueError("ssh_executable must be a non-empty path without NUL bytes")
        selected_cluster_id = cluster_id or host_alias
        if not _LOG_IDENTIFIER.fullmatch(selected_cluster_id):
            raise ValueError("cluster_id must be a safe non-empty logging identifier")

        self._host_alias = host_alias
        self._cluster_id = selected_cluster_id
        self._timeout_seconds = timeout_seconds
        self._ssh_executable = executable
        self._terminate_grace_seconds = terminate_grace_seconds

    @property
    def host_alias(self) -> str:
        return self._host_alias

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    @property
    def cluster_id(self) -> str:
        return self._cluster_id

    def build_command(
        self,
        remote_executable: str,
        arguments: Sequence[str] = (),
    ) -> tuple[str, ...]:
        """Build the exact local argument array passed to OpenSSH.

        OpenSSH sends its command operands to the remote user's shell. Joining
        one safely quoted remote-command operand prevents argument boundaries
        from becoming remote shell syntax.
        """

        remote_command = build_remote_command(remote_executable, arguments)
        return (
            self._ssh_executable,
            "-T",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            self._host_alias,
            remote_command,
        )

    async def execute(
        self,
        remote_executable: str,
        arguments: Sequence[str] = (),
        *,
        command_type: str | None = None,
        stdin_data: bytes | None = None,
    ) -> SshCommandResult:
        """Run one remote command and capture its output.

        Cancellation and timeouts terminate the local SSH child and drain its
        pipes before control returns to the caller.
        """

        if stdin_data is not None and len(stdin_data) > _MAX_STDIN_BYTES:
            raise ValueError("stdin_data exceeds the one MiB safety limit")

        argv = self.build_command(remote_executable, arguments)
        safe_command_type = _safe_command_type(remote_executable, command_type)
        started = time.perf_counter()

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=(
                    asyncio.subprocess.PIPE
                    if stdin_data is not None
                    else asyncio.subprocess.DEVNULL
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            duration = time.perf_counter() - started
            logger.warning(
                "ssh_command_connection_failure cluster_id=%s host=%s command_type=%s "
                "timeout=false exit_status=unavailable duration_ms=%.1f",
                self._cluster_id,
                self._host_alias,
                safe_command_type,
                duration * 1_000,
                extra={
                    "cluster_id": self._cluster_id,
                    "cluster_host": self._host_alias,
                    "command_type": safe_command_type,
                    "duration_seconds": duration,
                    "exit_status": None,
                    "timeout": False,
                },
            )
            raise ClusterConnectionError(
                "The local OpenSSH client could not be started.",
                host_alias=self._host_alias,
                remote_executable=remote_executable,
            ) from exc

        try:
            async with asyncio.timeout(self._timeout_seconds):
                stdout_bytes, stderr_bytes = await self._capture_bounded_output(
                    process,
                    stdin_data,
                )
        except _OutputLimitExceeded as exc:
            duration = time.perf_counter() - started
            logger.warning(
                "ssh_command_output_limit cluster_id=%s host=%s command_type=%s "
                "output_stream=%s output_limit_bytes=%d timeout=false "
                "exit_status=%s duration_ms=%.1f",
                self._cluster_id,
                self._host_alias,
                safe_command_type,
                exc.stream_name,
                MAX_CAPTURE_BYTES,
                process.returncode,
                duration * 1_000,
                extra={
                    "cluster_id": self._cluster_id,
                    "cluster_host": self._host_alias,
                    "command_type": safe_command_type,
                    "duration_seconds": duration,
                    "exit_status": process.returncode,
                    "timeout": False,
                    "output_stream": exc.stream_name,
                    "output_limit_bytes": MAX_CAPTURE_BYTES,
                },
            )
            raise RemoteCommandOutputLimitError(
                host_alias=self._host_alias,
                remote_executable=remote_executable,
                exit_code=process.returncode,
                stream_name=exc.stream_name,
                limit_bytes=MAX_CAPTURE_BYTES,
            ) from None
        except TimeoutError as exc:
            await self._cleanup_cancelled_process(process)
            duration = time.perf_counter() - started
            logger.warning(
                "ssh_command_timeout cluster_id=%s host=%s command_type=%s timeout=true "
                "timeout_seconds=%.3f exit_status=%s duration_ms=%.1f",
                self._cluster_id,
                self._host_alias,
                safe_command_type,
                self._timeout_seconds,
                process.returncode,
                duration * 1_000,
                extra={
                    "cluster_id": self._cluster_id,
                    "cluster_host": self._host_alias,
                    "command_type": safe_command_type,
                    "duration_seconds": duration,
                    "exit_status": process.returncode,
                    "timeout": True,
                    "timeout_seconds": self._timeout_seconds,
                },
            )
            raise RemoteCommandTimeoutError(
                "The remote command exceeded its configured timeout.",
                host_alias=self._host_alias,
                remote_executable=remote_executable,
                timeout_seconds=self._timeout_seconds,
            ) from exc
        except asyncio.CancelledError:
            await asyncio.shield(self._cleanup_cancelled_process(process))
            duration = time.perf_counter() - started
            logger.info(
                "ssh_command_cancelled cluster_id=%s host=%s command_type=%s "
                "timeout=false exit_status=%s duration_ms=%.1f",
                self._cluster_id,
                self._host_alias,
                safe_command_type,
                process.returncode,
                duration * 1_000,
                extra={
                    "cluster_id": self._cluster_id,
                    "cluster_host": self._host_alias,
                    "command_type": safe_command_type,
                    "duration_seconds": duration,
                    "exit_status": process.returncode,
                    "timeout": False,
                },
            )
            raise

        duration = time.perf_counter() - started
        stdout = _decode(stdout_bytes)
        stderr = _decode(stderr_bytes)
        exit_code = process.returncode
        if exit_code is None:
            raise RuntimeError("OpenSSH process completed without an exit status")

        log_extra = {
            "cluster_id": self._cluster_id,
            "cluster_host": self._host_alias,
            "command_type": safe_command_type,
            "duration_seconds": duration,
            "exit_status": exit_code,
            "timeout": False,
        }
        if exit_code == _SSH_CONNECTION_ERROR:
            logger.warning(
                "ssh_command_connection_failure cluster_id=%s host=%s command_type=%s "
                "timeout=false exit_status=%d duration_ms=%.1f",
                self._cluster_id,
                self._host_alias,
                safe_command_type,
                exit_code,
                duration * 1_000,
                extra=log_extra,
            )
            raise ClusterConnectionError(
                "OpenSSH could not connect to the configured cluster.",
                host_alias=self._host_alias,
                remote_executable=remote_executable,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )

        if exit_code != 0:
            logger.warning(
                "ssh_command_failure cluster_id=%s host=%s command_type=%s "
                "timeout=false exit_status=%d duration_ms=%.1f",
                self._cluster_id,
                self._host_alias,
                safe_command_type,
                exit_code,
                duration * 1_000,
                extra=log_extra,
            )
            raise RemoteCommandError(
                "The remote command returned a non-zero exit status.",
                host_alias=self._host_alias,
                remote_executable=remote_executable,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )

        logger.info(
            "ssh_command_complete cluster_id=%s host=%s command_type=%s "
            "timeout=false exit_status=%d duration_ms=%.1f",
            self._cluster_id,
            self._host_alias,
            safe_command_type,
            exit_code,
            duration * 1_000,
            extra=log_extra,
        )
        return SshCommandResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_seconds=duration,
        )

    @asynccontextmanager
    async def stream(
        self,
        remote_executable: str,
        arguments: Sequence[str] = (),
        *,
        command_type: str | None = None,
    ) -> AsyncIterator[SshByteStream]:
        """Stream one remote command until it exits or its consumer disconnects.

        Unlike :meth:`execute`, this intentionally has no wall-clock timeout.
        The context owns the child process and always terminates and drains it.
        """

        argv = self.build_command(remote_executable, arguments)
        safe_command_type = _safe_command_type(remote_executable, command_type)
        started = time.perf_counter()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise ClusterConnectionError(
                "The local OpenSSH client could not be started.",
                host_alias=self._host_alias,
                remote_executable=remote_executable,
            ) from exc

        if process.stderr is None:
            await self._cleanup_cancelled_process(process)
            raise RuntimeError("OpenSSH process did not expose a stderr pipe")
        stderr_task = asyncio.create_task(_read_stream_diagnostics(process.stderr))
        stream = SshByteStream(
            process,
            host_alias=self._host_alias,
            remote_executable=remote_executable,
            stderr_task=stderr_task,
        )
        logger.info(
            "ssh_stream_open cluster_id=%s host=%s command_type=%s",
            self._cluster_id,
            self._host_alias,
            safe_command_type,
            extra={
                "cluster_id": self._cluster_id,
                "cluster_host": self._host_alias,
                "command_type": safe_command_type,
            },
        )
        try:
            yield stream
        finally:
            cleanup_task = asyncio.create_task(self._close_stream(process, stderr_task))
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                await cleanup_task
                raise
            duration = time.perf_counter() - started
            logger.info(
                "ssh_stream_closed cluster_id=%s host=%s command_type=%s "
                "exit_status=%s duration_ms=%.1f",
                self._cluster_id,
                self._host_alias,
                safe_command_type,
                process.returncode,
                duration * 1_000,
                extra={
                    "cluster_id": self._cluster_id,
                    "cluster_host": self._host_alias,
                    "command_type": safe_command_type,
                    "duration_seconds": duration,
                    "exit_status": process.returncode,
                },
            )

    async def _close_stream(
        self,
        process: asyncio.subprocess.Process,
        stderr_task: asyncio.Task[bytes],
    ) -> None:
        stdout_drain = asyncio.create_task(_discard_stream(process.stdout))
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
        try:
            async with asyncio.timeout(self._terminate_grace_seconds):
                await process.wait()
        except TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()
        await asyncio.gather(stdout_drain, stderr_task, return_exceptions=True)

    async def _capture_bounded_output(
        self,
        process: asyncio.subprocess.Process,
        stdin_data: bytes | None,
    ) -> tuple[bytes, bytes]:
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("OpenSSH process did not expose output pipes")

        overflow_event = asyncio.Event()
        overflow_streams: set[_StreamName] = set()
        stdout_capture = bytearray()
        stderr_capture = bytearray()
        stdout_task = asyncio.create_task(
            _read_bounded_stream(
                process.stdout,
                "stdout",
                overflow_event,
                overflow_streams,
                stdout_capture,
            )
        )
        stderr_task = asyncio.create_task(
            _read_bounded_stream(
                process.stderr,
                "stderr",
                overflow_event,
                overflow_streams,
                stderr_capture,
            )
        )
        wait_task = asyncio.create_task(process.wait())
        overflow_task = asyncio.create_task(overflow_event.wait())
        stdin_task = (
            asyncio.create_task(_write_stdin(process, stdin_data))
            if stdin_data is not None
            else None
        )
        capture_tasks = [stdout_task, stderr_task, wait_task]
        if stdin_task is not None:
            capture_tasks.append(stdin_task)

        try:
            await asyncio.wait(
                (wait_task, overflow_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if overflow_event.is_set() and process.returncode is None:
                stdout_capture.clear()
                stderr_capture.clear()
                await self._terminate_and_drain_tasks(process, capture_tasks)
                raise _OutputLimitExceeded(overflow_streams)

            await wait_task
            await asyncio.gather(stdout_task, stderr_task)
            if stdin_task is not None:
                await stdin_task
            if overflow_event.is_set():
                stdout_capture.clear()
                stderr_capture.clear()
                raise _OutputLimitExceeded(overflow_streams)
            return bytes(stdout_capture), bytes(stderr_capture)
        except BaseException:
            for task in capture_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*capture_tasks, return_exceptions=True)
            raise
        finally:
            if not overflow_task.done():
                overflow_task.cancel()
            with suppress(asyncio.CancelledError):
                await overflow_task

    async def _terminate_and_drain_tasks(
        self,
        process: asyncio.subprocess.Process,
        tasks: Sequence[asyncio.Task[object]],
    ) -> None:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()

        drain = asyncio.gather(*tasks)
        try:
            async with asyncio.timeout(self._terminate_grace_seconds):
                await asyncio.shield(drain)
        except TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await drain

    async def _cleanup_cancelled_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            await _drain_process(process)
            return

        try:
            process.terminate()
        except ProcessLookupError:
            await _drain_process(process)
            return

        try:
            async with asyncio.timeout(self._terminate_grace_seconds):
                await _drain_process(process)
        except TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await _drain_process(process)


def build_remote_command(
    remote_executable: str,
    arguments: Sequence[str] = (),
) -> str:
    """Safely quote a remote executable and each of its fixed arguments."""

    command_parts = (remote_executable, *arguments)
    if not remote_executable:
        raise ValueError("remote_executable must not be empty")
    if any("\x00" in part for part in command_parts):
        raise ValueError("remote command values must not contain NUL bytes")
    return shlex.join(command_parts)


def _decode(value: bytes | None) -> str:
    return (value or b"").decode("utf-8", errors="replace")


async def _read_bounded_stream(
    stream: asyncio.StreamReader,
    stream_name: _StreamName,
    overflow_event: asyncio.Event,
    overflow_streams: set[_StreamName],
    captured: bytearray,
) -> None:
    while chunk := await stream.read(_STREAM_READ_BYTES):
        if overflow_event.is_set():
            continue
        remaining = MAX_CAPTURE_BYTES - len(captured)
        if len(chunk) > remaining:
            captured.clear()
            overflow_streams.add(stream_name)
            overflow_event.set()
            continue
        captured.extend(chunk)


async def _write_stdin(
    process: asyncio.subprocess.Process,
    stdin_data: bytes,
) -> None:
    if process.stdin is None:
        raise RuntimeError("OpenSSH process did not expose an input pipe")

    try:
        process.stdin.write(stdin_data)
        await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        process.stdin.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await process.stdin.wait_closed()


async def _drain_process(process: asyncio.subprocess.Process) -> None:
    async def discard(stream: asyncio.StreamReader | None) -> None:
        if stream is None:
            return
        while await stream.read(_STREAM_READ_BYTES):
            pass

    await asyncio.gather(
        process.wait(),
        discard(process.stdout),
        discard(process.stderr),
    )


async def _discard_stream(stream: asyncio.StreamReader | None) -> None:
    if stream is None:
        return
    while await stream.read(_STREAM_READ_BYTES):
        pass


async def _read_stream_diagnostics(stream: asyncio.StreamReader) -> bytes:
    captured = bytearray()
    while chunk := await stream.read(_STREAM_READ_BYTES):
        remaining = _MAX_STREAM_DIAGNOSTIC_BYTES - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])
    return bytes(captured)


def _safe_command_type(remote_executable: str, command_type: str | None) -> str:
    if command_type is not None:
        if not _LOG_IDENTIFIER.fullmatch(command_type):
            raise ValueError("command_type must be a safe non-empty logging identifier")
        return command_type

    executable_name = Path(remote_executable).name
    return executable_name if _LOG_IDENTIFIER.fullmatch(executable_name) else "remote"
