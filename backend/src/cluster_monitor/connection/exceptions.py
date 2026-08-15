"""Typed failures raised by the local OpenSSH execution layer."""

from __future__ import annotations


class SshCommandError(Exception):
    """Base class carrying safe command metadata and captured process streams."""

    def __init__(
        self,
        message: str,
        *,
        host_alias: str,
        remote_executable: str,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.host_alias = host_alias
        self.remote_executable = remote_executable
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class ClusterConnectionError(SshCommandError):
    """OpenSSH could not establish or maintain the cluster connection."""


class RemoteCommandError(SshCommandError):
    """SSH connected, but the remote command returned a non-zero status."""


class RemoteCommandTimeoutError(SshCommandError):
    """The configured wall-clock timeout expired."""

    def __init__(
        self,
        message: str,
        *,
        host_alias: str,
        remote_executable: str,
        timeout_seconds: float,
    ) -> None:
        super().__init__(
            message,
            host_alias=host_alias,
            remote_executable=remote_executable,
        )
        self.timeout_seconds = timeout_seconds
