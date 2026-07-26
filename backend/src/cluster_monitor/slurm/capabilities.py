"""Slurm version and machine-readable output capability detection."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from cluster_monitor.connection import RemoteCommandError, SshCommandResult
from cluster_monitor.logging import get_logger
from cluster_monitor.slurm.commands import (
    SlurmCommand,
    build_sacct_json_probe,
    build_sinfo_json_probe,
    build_squeue_json_probe,
    build_version_command,
)

logger = get_logger("slurm.capabilities")

_VERSION_TOKEN = r"\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9._-]+)?"
_LABELED_SLURM_VERSION = re.compile(
    rf"^[ \t]*slurm(?:-wlm)?[ \t]+(?P<version>{_VERSION_TOKEN})[ \t]*$",
    flags=re.IGNORECASE | re.MULTILINE,
)
_BARE_SLURM_VERSION = re.compile(rf"^(?P<version>{_VERSION_TOKEN})$")
_EXPECTED_JSON_KEYS = {
    # Slurm 23.11+ data_parser responses use ``sinfo`` while older releases
    # exposed node/partition collections directly.
    "sinfo": frozenset({"sinfo", "nodes", "partitions"}),
    "squeue": frozenset({"jobs"}),
    "sacct": frozenset({"jobs"}),
}


class RemoteCommandExecutor(Protocol):
    async def execute(
        self,
        remote_executable: str,
        arguments: Sequence[str] = (),
        *,
        command_type: str | None = None,
        stdin_data: bytes | None = None,
    ) -> SshCommandResult: ...


@dataclass(frozen=True, slots=True)
class SlurmCapabilities:
    version: str
    sinfo_json: bool
    squeue_json: bool
    sacct_json: bool


class SlurmVersionDetectionError(ValueError):
    """The reported Slurm version did not contain a recognizable version."""


async def detect_slurm_capabilities(executor: RemoteCommandExecutor) -> SlurmCapabilities:
    """Detect version and usable JSON support without masking transport errors.

    Callers should retain the returned immutable value for the backend lifetime.
    Each JSON probe uses a narrow, documented Slurm filter to avoid discarding a
    full queue or accounting response.
    """

    version_result = await _execute(executor, build_version_command())
    version = parse_slurm_version(version_result.stdout)

    sinfo_json = await _supports_json(executor, build_sinfo_json_probe())
    squeue_json = await _supports_json(executor, build_squeue_json_probe())
    sacct_json = await _supports_json(executor, build_sacct_json_probe())
    logger.info(
        "slurm_capabilities_detected version=%s sinfo_json=%s squeue_json=%s sacct_json=%s",
        version,
        sinfo_json,
        squeue_json,
        sacct_json,
        extra={
            "slurm_version": version,
            "sinfo_json": sinfo_json,
            "squeue_json": squeue_json,
            "sacct_json": sacct_json,
        },
    )
    return SlurmCapabilities(
        version=version,
        sinfo_json=sinfo_json,
        squeue_json=squeue_json,
        sacct_json=sacct_json,
    )


def parse_slurm_version(output: str) -> str:
    stripped = output.strip()
    match = _LABELED_SLURM_VERSION.search(stripped)
    if match is None:
        match = _BARE_SLURM_VERSION.fullmatch(stripped)
    if match is None:
        raise SlurmVersionDetectionError("Could not parse the Slurm version response.")
    return match.group("version")


async def _supports_json(
    executor: RemoteCommandExecutor,
    command: SlurmCommand,
) -> bool:
    try:
        result = await _execute(executor, command)
    except RemoteCommandError:
        return False

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict) or payload.get("errors"):
        return False
    expected_keys = _EXPECTED_JSON_KEYS[command.executable]
    return bool(expected_keys & payload.keys())


async def _execute(
    executor: RemoteCommandExecutor,
    command: SlurmCommand,
) -> SshCommandResult:
    return await executor.execute(
        command.executable,
        command.arguments,
        command_type=command.command_type,
    )
