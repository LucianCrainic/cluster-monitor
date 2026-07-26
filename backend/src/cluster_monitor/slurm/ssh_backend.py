"""Slurm backend executed through a configured OpenSSH alias."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import ValidationError

from cluster_monitor.config import ClusterConfig
from cluster_monitor.connection import (
    ClusterConnectionError,
    OpenSshExecutor,
    RemoteCommandError,
    RemoteCommandOutputLimitError,
    RemoteCommandTimeoutError,
    SshCommandError,
)
from cluster_monitor.exceptions import (
    ClusterMonitorError,
    ClusterUnavailableError,
    JobActionForbiddenError,
    JobActionRejectedError,
    JobActionScopeUnsupportedError,
    JobActionsDisabledError,
    JobActionUncertainError,
    JobNotFoundError,
)
from cluster_monitor.logging import get_logger
from cluster_monitor.models import (
    BackendType,
    Cluster,
    ClusterOverview,
    ConnectionStatus,
    Job,
    JobCancellationReceipt,
    JobDetails,
    JobState,
    JobSubmissionReceipt,
    JobSubmissionRequest,
    Node,
    NodeState,
    Partition,
)
from cluster_monitor.slurm.capabilities import (
    RemoteCommandExecutor,
    SlurmCapabilities,
    SlurmVersionDetectionError,
    detect_slurm_capabilities,
)
from cluster_monitor.slurm.commands import (
    SlurmCommand,
    build_nodes_json_command,
    build_nodes_text_command,
    build_partitions_json_command,
    build_partitions_text_command,
    build_remote_user_command,
    build_sacct_json_command,
    build_sacct_text_command,
    build_sbatch_command,
    build_scancel_command,
    build_squeue_json_command,
    build_squeue_text_command,
)
from cluster_monitor.slurm.json_parser import (
    SlurmJsonParseError,
    parse_nodes_json,
    parse_partitions_json,
    parse_sacct_job_details_json,
    parse_sacct_jobs_json,
    parse_squeue_jobs_json,
)
from cluster_monitor.slurm.text_parser import (
    SlurmTextParseError,
    parse_nodes_text,
    parse_partitions_text,
    parse_sacct_jobs_text,
    parse_squeue_jobs_text,
)

logger = get_logger("slurm.ssh_backend")

_REMOTE_USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
_CACHE_SECONDS = 2.0
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class _TimedValue[T]:
    value: T
    expires_at: float


class SshSlurmBackend:
    """Normalize Slurm data and perform narrowly scoped job mutations."""

    def __init__(
        self,
        config: ClusterConfig,
        *,
        executor: RemoteCommandExecutor | None = None,
        cache_ttl_seconds: float = _CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if config.ssh_host is None:
            raise ValueError("An SSH backend requires a configured ssh_host alias.")
        if cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds must not be negative")

        self._config = config
        self._executor = executor or OpenSshExecutor(
            config.ssh_host,
            cluster_id=config.id,
            timeout_seconds=config.command_timeout_seconds,
        )
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock

        self._capabilities: SlurmCapabilities | None = None
        self._remote_user: str | None = None
        self._last_successful_refresh: datetime | None = None
        self._last_error: str | None = None

        self._capabilities_lock = asyncio.Lock()
        self._remote_user_lock = asyncio.Lock()
        self._partitions_lock = asyncio.Lock()
        self._nodes_lock = asyncio.Lock()
        self._jobs_lock = asyncio.Lock()
        self._history_lock = asyncio.Lock()

        self._partitions_cache: _TimedValue[list[Partition]] | None = None
        self._nodes_cache: _TimedValue[list[Node]] | None = None
        self._jobs_cache: _TimedValue[list[Job]] | None = None
        self._history_cache: _TimedValue[list[Job]] | None = None

    async def get_cluster(self) -> Cluster:
        try:
            capabilities = await self._get_capabilities()
        except _EXPECTED_BACKEND_ERRORS as exc:
            message = self._safe_error_message(exc)
            self._record_error(message)
            return Cluster(
                id=self._config.id,
                name=self._config.name,
                backend=BackendType.SSH,
                connection_status=ConnectionStatus.UNAVAILABLE,
                job_actions_enabled=self._config.allow_job_actions,
                last_successful_refresh=self._last_successful_refresh,
                last_error=message,
            )

        return Cluster(
            id=self._config.id,
            name=self._config.name,
            backend=BackendType.SSH,
            connection_status=ConnectionStatus.CONNECTED,
            job_actions_enabled=self._config.allow_job_actions,
            slurm_version=capabilities.version,
            last_successful_refresh=self._last_successful_refresh,
            last_error=self._last_error,
        )

    async def get_overview(self) -> ClusterOverview:
        async def load() -> ClusterOverview:
            capabilities = await self._get_capabilities()
            nodes, jobs = await asyncio.gather(self.get_nodes(), self.get_jobs())
            idle_nodes = sum(node.state is NodeState.IDLE for node in nodes)
            allocated_nodes = sum(
                node.state in {NodeState.ALLOCATED, NodeState.MIXED, NodeState.COMPLETING}
                for node in nodes
            )
            unavailable_nodes = max(0, len(nodes) - idle_nodes - allocated_nodes)
            refreshed_at = self._record_success()
            return ClusterOverview(
                cluster_id=self._config.id,
                connection_status=ConnectionStatus.CONNECTED,
                slurm_version=capabilities.version,
                total_nodes=len(nodes),
                idle_nodes=idle_nodes,
                allocated_nodes=allocated_nodes,
                unavailable_nodes=unavailable_nodes,
                running_jobs=sum(job.state is JobState.RUNNING for job in jobs),
                pending_jobs=sum(job.state is JobState.PENDING for job in jobs),
                last_refresh=refreshed_at,
            )

        return await self._guard(load)

    async def get_partitions(self) -> list[Partition]:
        async def load() -> list[Partition]:
            async with self._partitions_lock:
                cached = self._fresh(self._partitions_cache)
                if cached is not None:
                    return _copy_models(cached)

                capabilities = await self._get_capabilities()
                partitions = await self._load_partitions(capabilities)
                self._partitions_cache = self._timed(partitions)
                self._record_success()
                return _copy_models(partitions)

        return await self._guard(load)

    async def get_nodes(self) -> list[Node]:
        async def load() -> list[Node]:
            async with self._nodes_lock:
                cached = self._fresh(self._nodes_cache)
                if cached is not None:
                    return _copy_models(cached)

                capabilities = await self._get_capabilities()
                nodes = await self._load_nodes(capabilities)
                self._nodes_cache = self._timed(nodes)
                self._record_success()
                return _copy_models(nodes)

        return await self._guard(load)

    async def get_jobs(self, user: str | None = None) -> list[Job]:
        async def load() -> list[Job]:
            selected_user = await self._selected_user(user)
            use_default_cache = user is None
            if not use_default_cache:
                jobs = await self._load_jobs(selected_user)
                self._record_success()
                return jobs

            async with self._jobs_lock:
                cached = self._fresh(self._jobs_cache)
                if cached is not None:
                    return _copy_models(cached)
                jobs = await self._load_jobs(selected_user)
                self._jobs_cache = self._timed(jobs)
                self._record_success()
                return _copy_models(jobs)

        return await self._guard(load)

    async def get_job(self, job_id: str) -> JobDetails:
        async def load() -> JobDetails:
            selected_user = await self._selected_user(None)
            capabilities = await self._get_capabilities()
            details: JobDetails | None = None
            accounting_json_succeeded = False

            if capabilities.sacct_json:
                try:
                    output = await self._execute(
                        build_sacct_json_command(selected_user, job_id=job_id)
                    )
                    details = parse_sacct_job_details_json(output, job_id)
                    accounting_json_succeeded = True
                except (RemoteCommandError, SlurmJsonParseError):
                    logger.info(
                        "slurm_json_fallback cluster_id=%s command_type=sacct_job_json",
                        self._config.id,
                    )

            if details is None and not accounting_json_succeeded:
                output = await self._execute(build_sacct_text_command(selected_user, job_id=job_id))
                historical = parse_sacct_jobs_text(output)
                match = next((job for job in historical if job.job_id == job_id), None)
                if match is not None:
                    details = _job_details(match)

            if details is None:
                active = await self.get_jobs()
                match = next((job for job in active if job.job_id == job_id), None)
                if match is not None:
                    details = _job_details(match)

            if details is None:
                raise JobNotFoundError(self._config.id, job_id)

            self._record_success()
            return details

        return await self._guard(load)

    async def get_recent_jobs(
        self,
        user: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        async def load() -> list[Job]:
            selected_user = await self._selected_user(user)
            use_default_cache = user is None
            if not use_default_cache:
                jobs = await self._load_recent_jobs(selected_user)
                self._record_success()
                return jobs[:limit]

            async with self._history_lock:
                cached = self._fresh(self._history_cache)
                if cached is None:
                    jobs = await self._load_recent_jobs(selected_user)
                    self._history_cache = self._timed(jobs)
                    self._record_success()
                else:
                    jobs = cached
                return _copy_models(jobs[:limit])

        return await self._guard(load)

    async def submit_job(self, request: JobSubmissionRequest) -> JobSubmissionReceipt:
        async def load() -> JobSubmissionReceipt:
            self._require_job_actions()
            await self._get_capabilities()
            command = build_sbatch_command(request)
            try:
                output = await self._execute(
                    command,
                    stdin_data=request.script.encode("utf-8"),
                )
            except (
                ClusterConnectionError,
                RemoteCommandOutputLimitError,
                RemoteCommandTimeoutError,
            ):
                raise JobActionUncertainError(self._config.id, "submit") from None
            except RemoteCommandError:
                raise JobActionRejectedError(self._config.id, "submit") from None

            parsed_receipt = _parse_submitted_job_receipt(output)
            if parsed_receipt is None:
                raise JobActionUncertainError(self._config.id, "submit")
            job_id, scheduler_cluster = parsed_receipt

            submitted_at = self._record_success()
            self._invalidate_job_caches()
            return JobSubmissionReceipt(
                cluster_id=self._config.id,
                job_id=job_id,
                submitted_at=submitted_at,
                scheduler_cluster=scheduler_cluster,
            )

        return await self._guard(load)

    async def cancel_job(self, job_id: str) -> JobCancellationReceipt:
        async def load() -> JobCancellationReceipt:
            self._require_job_actions()
            try:
                command = build_scancel_command(job_id)
            except ValueError:
                raise JobActionRejectedError(
                    self._config.id,
                    "cancel",
                    job_id=job_id,
                ) from None
            job = await self.get_job(job_id)
            selected_user = await self._selected_user(None)
            if job.user != selected_user:
                raise JobActionForbiddenError(self._config.id, job_id)
            if job.array_job_id is not None:
                raise JobActionScopeUnsupportedError(
                    self._config.id,
                    job_id,
                    "array",
                )
            if job.heterogeneous_job_id is not None:
                raise JobActionScopeUnsupportedError(
                    self._config.id,
                    job_id,
                    "heterogeneous",
                )
            if job.state not in {
                JobState.PENDING,
                JobState.RUNNING,
                JobState.SUSPENDED,
            }:
                raise JobActionRejectedError(
                    self._config.id,
                    "cancel",
                    job_id=job_id,
                )

            try:
                await self._execute(command)
            except (
                ClusterConnectionError,
                RemoteCommandOutputLimitError,
                RemoteCommandTimeoutError,
            ):
                raise JobActionUncertainError(
                    self._config.id,
                    "cancel",
                    job_id=job_id,
                ) from None
            except RemoteCommandError:
                raise JobActionRejectedError(
                    self._config.id,
                    "cancel",
                    job_id=job_id,
                ) from None

            requested_at = self._record_success()
            self._invalidate_job_caches()
            return JobCancellationReceipt(
                cluster_id=self._config.id,
                job_id=job_id,
                requested_at=requested_at,
            )

        return await self._guard(load)

    async def _get_capabilities(self) -> SlurmCapabilities:
        if self._capabilities is not None:
            return self._capabilities
        async with self._capabilities_lock:
            if self._capabilities is None:
                self._capabilities = await detect_slurm_capabilities(self._executor)
                self._record_success()
            return self._capabilities

    async def _selected_user(self, requested_user: str | None) -> str:
        if requested_user is not None:
            if not _REMOTE_USER.fullmatch(requested_user):
                raise ValueError("The requested Slurm user is invalid.")
            return requested_user
        if self._config.slurm_user != "current":
            return self._config.slurm_user
        if self._remote_user is not None:
            return self._remote_user

        async with self._remote_user_lock:
            if self._remote_user is None:
                output = (await self._execute(build_remote_user_command())).strip()
                if not _REMOTE_USER.fullmatch(output):
                    raise ValueError("The remote login user could not be determined.")
                self._remote_user = output
            return self._remote_user

    async def _load_partitions(self, capabilities: SlurmCapabilities) -> list[Partition]:
        if capabilities.sinfo_json:
            try:
                return parse_partitions_json(await self._execute(build_partitions_json_command()))
            except (RemoteCommandError, SlurmJsonParseError):
                logger.info(
                    "slurm_json_fallback cluster_id=%s command_type=sinfo_partitions_json",
                    self._config.id,
                )
        return parse_partitions_text(await self._execute(build_partitions_text_command()))

    async def _load_nodes(self, capabilities: SlurmCapabilities) -> list[Node]:
        if capabilities.sinfo_json:
            try:
                return parse_nodes_json(await self._execute(build_nodes_json_command()))
            except (RemoteCommandError, SlurmJsonParseError):
                logger.info(
                    "slurm_json_fallback cluster_id=%s command_type=sinfo_nodes_json",
                    self._config.id,
                )
        return parse_nodes_text(await self._execute(build_nodes_text_command()))

    async def _load_jobs(self, selected_user: str) -> list[Job]:
        capabilities = await self._get_capabilities()
        if capabilities.squeue_json:
            try:
                return parse_squeue_jobs_json(
                    await self._execute(build_squeue_json_command(selected_user))
                )
            except (RemoteCommandError, SlurmJsonParseError):
                logger.info(
                    "slurm_json_fallback cluster_id=%s command_type=squeue_jobs_json",
                    self._config.id,
                )
        return parse_squeue_jobs_text(await self._execute(build_squeue_text_command(selected_user)))

    async def _load_recent_jobs(self, selected_user: str) -> list[Job]:
        capabilities = await self._get_capabilities()
        if capabilities.sacct_json:
            try:
                return parse_sacct_jobs_json(
                    await self._execute(build_sacct_json_command(selected_user))
                )
            except (RemoteCommandError, SlurmJsonParseError):
                logger.info(
                    "slurm_json_fallback cluster_id=%s command_type=sacct_jobs_json",
                    self._config.id,
                )
        return parse_sacct_jobs_text(await self._execute(build_sacct_text_command(selected_user)))

    async def _execute(
        self,
        command: SlurmCommand,
        *,
        stdin_data: bytes | None = None,
    ) -> str:
        result = await self._executor.execute(
            command.executable,
            command.arguments,
            command_type=command.command_type,
            stdin_data=stdin_data,
        )
        return result.stdout

    async def _guard(self, operation: Callable[[], Awaitable[_T]]) -> _T:
        try:
            return await operation()
        except ClusterMonitorError:
            raise
        except _EXPECTED_BACKEND_ERRORS as exc:
            message = self._safe_error_message(exc)
            self._record_error(message)
            raise ClusterUnavailableError(self._config.id, message) from None

    def _safe_error_message(self, exc: Exception) -> str:
        if isinstance(exc, RemoteCommandTimeoutError):
            timeout = self._config.command_timeout_seconds
            return f"The cluster did not answer the request within {timeout:g} seconds."
        if isinstance(exc, ClusterConnectionError):
            return (
                "OpenSSH could not reach the cluster. Check the VPN and the reusable "
                "SSH connection, then try again."
            )
        if isinstance(exc, RemoteCommandError):
            return "A required read-only Slurm command failed on the cluster."
        return "The cluster returned a Slurm response this application could not normalize."

    def _record_success(self) -> datetime:
        refreshed_at = datetime.now(UTC)
        self._last_successful_refresh = refreshed_at
        self._last_error = None
        return refreshed_at

    def _record_error(self, message: str) -> None:
        self._last_error = message

    def _invalidate_job_caches(self) -> None:
        self._jobs_cache = None
        self._history_cache = None

    def _require_job_actions(self) -> None:
        if not self._config.allow_job_actions:
            raise JobActionsDisabledError(self._config.id)

    def _timed(self, value: _T) -> _TimedValue[_T]:
        return _TimedValue(value=value, expires_at=self._clock() + self._cache_ttl_seconds)

    def _fresh(self, value: _TimedValue[_T] | None) -> _T | None:
        if value is None or value.expires_at <= self._clock():
            return None
        return value.value


_EXPECTED_BACKEND_ERRORS = (
    SshCommandError,
    SlurmVersionDetectionError,
    SlurmJsonParseError,
    SlurmTextParseError,
    ValidationError,
    ValueError,
)


def _copy_models[T](values: list[T]) -> list[T]:
    copied: list[T] = []
    for value in values:
        model_copy = getattr(value, "model_copy", None)
        copied.append(model_copy(deep=True) if callable(model_copy) else value)
    return copied


def _job_details(job: Job) -> JobDetails:
    return JobDetails(
        **job.model_dump(),
        allocation_details={
            "nodes": job.nodes,
            "cpus": job.requested_cpus,
            "memory_mb": job.requested_memory_mb,
            "gpus": job.requested_gpus,
        },
    )


def _parse_submitted_job_receipt(output: str) -> tuple[str, str | None] | None:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    match = re.fullmatch(
        r"(?P<job_id>[1-9][0-9]*)(?:;(?P<cluster>[A-Za-z0-9_.-]{1,255}))?",
        lines[0],
    )
    if match is None:
        return None
    return match.group("job_id"), match.group("cluster")
