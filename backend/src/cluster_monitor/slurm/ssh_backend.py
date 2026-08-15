"""Slurm backend executed through a configured OpenSSH alias."""

from __future__ import annotations

import asyncio
import codecs
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

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
    FileBrowsingDisabledError,
    JobActionForbiddenError,
    JobActionRejectedError,
    JobActionScopeUnsupportedError,
    JobActionsDisabledError,
    JobActionUncertainError,
    JobLogAccessForbiddenError,
    JobLogIdentifierUnsupportedError,
    JobLogScopeAmbiguousError,
    JobLogScopeUnsupportedError,
    JobLogUnavailableError,
    JobNotFoundError,
)
from cluster_monitor.logging import get_logger
from cluster_monitor.models import (
    BackendType,
    Cluster,
    ClusterOverview,
    ClusterTopology,
    ConnectionStatus,
    Job,
    JobCancellationReceipt,
    JobDetails,
    JobLogChunkEvent,
    JobLogCompleteEvent,
    JobLogErrorEvent,
    JobLogEvent,
    JobLogMetadataEvent,
    JobLogSession,
    JobLogSource,
    JobLogStatusEvent,
    JobState,
    JobSubmissionReceipt,
    JobSubmissionRequest,
    Node,
    NodeState,
    Partition,
    RemoteDirectory,
    RemoteDirectoryRequest,
    RemoteFilePreview,
    RemoteFilePreviewRequest,
)
from cluster_monitor.slurm.capabilities import (
    RemoteCommandExecutor,
    SlurmCapabilities,
    SlurmVersionDetectionError,
    detect_slurm_capabilities,
)
from cluster_monitor.slurm.commands import (
    SlurmCommand,
    build_file_test_command,
    build_nodes_json_command,
    build_nodes_text_command,
    build_partitions_json_command,
    build_partitions_text_command,
    build_remote_files_command,
    build_remote_user_command,
    build_sacct_job_logs_text_command,
    build_sacct_json_command,
    build_sacct_text_command,
    build_sbatch_command,
    build_scancel_command,
    build_scontrol_job_json_command,
    build_scontrol_job_text_command,
    build_scontrol_nodes_json_command,
    build_scontrol_partitions_json_command,
    build_squeue_json_command,
    build_squeue_text_command,
    build_tail_command,
    build_topology_command,
)
from cluster_monitor.slurm.job_logs import (
    JobLogMetadata,
    JobLogMetadataParseError,
    metadata_from_job_details,
    overlay_metadata,
    parse_sacct_job_logs_text,
    parse_scontrol_job_logs_json,
    parse_scontrol_job_logs_text,
    resolve_log_paths,
    validate_log_job_id,
)
from cluster_monitor.slurm.json_parser import (
    SlurmJsonParseError,
    parse_nodes_json,
    parse_partitions_json,
    parse_sacct_job_details_json,
    parse_sacct_jobs_json,
    parse_squeue_jobs_json,
)
from cluster_monitor.slurm.remote_files import (
    parse_remote_directory,
    parse_remote_file_preview,
    validate_remote_path,
)
from cluster_monitor.slurm.text_parser import (
    SlurmTextParseError,
    parse_nodes_text,
    parse_partitions_text,
    parse_sacct_jobs_text,
    parse_squeue_jobs_text,
)
from cluster_monitor.slurm.topology import (
    SlurmTopologyParseError,
    build_cluster_topology,
    overlay_partition_details,
    parse_topology_text,
)

logger = get_logger("slurm.ssh_backend")

_REMOTE_USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
_CACHE_SECONDS = 2.0
_LOG_INITIAL_LINES = 200
_LOG_STATUS_POLL_SECONDS = 5.0
_LOG_FINAL_DRAIN_SECONDS = 1.0
_LOG_MAX_POLL_FAILURES = 3
_LOG_QUEUE_CHUNKS = 128
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
                file_browser_enabled=self._config.allow_file_browsing,
                last_successful_refresh=self._last_successful_refresh,
                last_error=message,
            )

        return Cluster(
            id=self._config.id,
            name=self._config.name,
            backend=BackendType.SSH,
            connection_status=ConnectionStatus.CONNECTED,
            job_actions_enabled=self._config.allow_job_actions,
            file_browser_enabled=self._config.allow_file_browsing,
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

    async def get_topology(self) -> ClusterTopology:
        async def load() -> ClusterTopology:
            partitions, nodes = await asyncio.gather(self.get_partitions(), self.get_nodes())
            physical = parse_topology_text("")
            try:
                physical = parse_topology_text(await self._execute(build_topology_command()))
            except (RemoteCommandError, SlurmTopologyParseError):
                logger.info(
                    "slurm_topology_fallback cluster_id=%s",
                    self._config.id,
                )
            captured_at = self._record_success()
            return build_cluster_topology(
                self._config.id,
                partitions,
                nodes,
                physical,
                captured_at,
            )

        return await self._guard(load)

    async def list_remote_directory(
        self,
        request: RemoteDirectoryRequest,
    ) -> RemoteDirectory:
        async def load() -> RemoteDirectory:
            self._require_file_browsing()
            validate_remote_path(
                request.path,
                self._config.id,
                allow_login_directory=True,
            )
            output = await self._execute(
                build_remote_files_command(
                    "list",
                    request.path,
                    show_hidden=request.show_hidden,
                )
            )
            directory = parse_remote_directory(output, self._config.id)
            self._record_success()
            return directory

        return await self._guard(load)

    async def preview_remote_file(
        self,
        request: RemoteFilePreviewRequest,
    ) -> RemoteFilePreview:
        async def load() -> RemoteFilePreview:
            self._require_file_browsing()
            validate_remote_path(
                request.path,
                self._config.id,
                allow_login_directory=False,
            )
            output = await self._execute(build_remote_files_command("preview", request.path))
            preview = parse_remote_file_preview(output, self._config.id)
            self._record_success()
            return preview

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

    async def open_job_log_stream(self, job_id: str) -> JobLogSession:
        """Resolve and authorize log files before sending SSE response headers."""

        try:
            validate_log_job_id(job_id)
        except ValueError:
            raise JobLogIdentifierUnsupportedError(self._config.id, job_id) from None

        async def load() -> JobLogSession:
            remote_user = await self._get_remote_user()
            metadata = await self._resolve_job_log_metadata(job_id, remote_user)
            if metadata.user != remote_user:
                raise JobLogAccessForbiddenError(self._config.id, job_id)
            if metadata.ambiguous_array_leader:
                raise JobLogScopeAmbiguousError(self._config.id, job_id)
            if metadata.heterogeneous_job_id is not None:
                raise JobLogScopeUnsupportedError(self._config.id, job_id)
            try:
                paths = resolve_log_paths(metadata)
            except JobLogMetadataParseError as exc:
                raise JobLogUnavailableError(self._config.id, job_id, str(exc)) from None
            if metadata.terminal:
                paths = await self._ready_log_paths(paths)
                if not paths:
                    raise JobLogUnavailableError(self._config.id, job_id)
            self._record_success()
            return JobLogSession(events=self._stream_job_log_events(metadata, remote_user))

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
        return await self._get_remote_user()

    async def _get_remote_user(self) -> str:
        if self._remote_user is not None:
            return self._remote_user

        async with self._remote_user_lock:
            if self._remote_user is None:
                output = (await self._execute(build_remote_user_command())).strip()
                if not _REMOTE_USER.fullmatch(output):
                    raise ValueError("The remote login user could not be determined.")
                self._remote_user = output
            return self._remote_user

    async def _resolve_job_log_metadata(
        self,
        job_id: str,
        remote_user: str,
    ) -> JobLogMetadata:
        """Resolve live state with scontrol and expanded paths with sacct."""

        primary: JobLogMetadata | None = None
        try:
            primary = parse_scontrol_job_logs_json(
                await self._execute(build_scontrol_job_json_command(job_id)),
                job_id,
            )
        except (RemoteCommandError, JobLogMetadataParseError):
            logger.info(
                "slurm_log_metadata_fallback cluster_id=%s command_type=scontrol_job_logs_json",
                self._config.id,
            )
        if primary is None:
            with suppress(RemoteCommandError, JobLogMetadataParseError):
                primary = parse_scontrol_job_logs_text(
                    await self._execute(build_scontrol_job_text_command(job_id)),
                    job_id,
                )

        expanded: JobLogMetadata | None = None
        capabilities = await self._get_capabilities()
        if capabilities.sacct_json:
            try:
                details = parse_sacct_job_details_json(
                    await self._execute(
                        build_sacct_json_command(
                            remote_user,
                            job_id=job_id,
                            expand_patterns=True,
                        )
                    ),
                    job_id,
                )
                if details is not None:
                    expanded = metadata_from_job_details(details)
            except (RemoteCommandError, SlurmJsonParseError):
                logger.info(
                    "slurm_log_metadata_fallback cluster_id=%s command_type=sacct_job_logs_json",
                    self._config.id,
                )
        if expanded is None:
            with suppress(RemoteCommandError, JobLogMetadataParseError):
                expanded = parse_sacct_job_logs_text(
                    await self._execute(build_sacct_job_logs_text_command(remote_user, job_id)),
                    job_id,
                )

        if primary is not None and expanded is not None:
            return overlay_metadata(primary, expanded)
        if primary is not None:
            return primary
        if expanded is not None:
            return expanded
        raise JobNotFoundError(self._config.id, job_id)

    async def _stream_job_log_events(
        self,
        metadata: JobLogMetadata,
        remote_user: str,
    ) -> AsyncIterator[JobLogEvent]:
        sequence = 0
        current = metadata
        try:
            paths = resolve_log_paths(current)
        except JobLogMetadataParseError as exc:
            yield JobLogErrorEvent(
                code="job_log_unavailable",
                message=str(exc),
                retryable=False,
            )
            yield JobLogCompleteEvent(reason="unavailable")
            return

        if current.terminal:
            ready = await self._ready_log_paths(paths)
            if not ready:
                yield JobLogErrorEvent(
                    code="job_log_unavailable",
                    message="The job output files are no longer readable.",
                    retryable=False,
                )
                yield JobLogCompleteEvent(reason="unavailable")
                return
            yield self._metadata_event(current, ready)
            yield JobLogStatusEvent(
                status="finalizing",
                message="Loading the final job output.",
            )
            snapshot_failed = False
            async for event in self._stream_log_snapshot(ready, sequence):
                if isinstance(event, JobLogChunkEvent):
                    sequence = event.sequence
                elif isinstance(event, JobLogErrorEvent):
                    snapshot_failed = True
                yield event
            yield JobLogCompleteEvent(
                reason="unavailable" if snapshot_failed else "snapshot_complete"
            )
            return

        yield self._metadata_event(current, paths)
        waiting_sent = False
        failures = 0
        while True:
            ready = await self._ready_log_paths(paths)
            if paths and len(ready) == len(paths):
                break
            if not waiting_sent:
                yield JobLogStatusEvent(
                    status="waiting",
                    message="Waiting for Slurm to create the job output files.",
                )
                waiting_sent = True
            await asyncio.sleep(_LOG_STATUS_POLL_SECONDS)
            try:
                current = await self._resolve_job_log_metadata(current.job_id, remote_user)
                failures = 0
                paths = resolve_log_paths(current)
            except (ClusterMonitorError, JobLogMetadataParseError):
                failures += 1
                if failures >= _LOG_MAX_POLL_FAILURES:
                    yield JobLogErrorEvent(
                        code="job_log_metadata_unavailable",
                        message="The job state could not be refreshed.",
                        retryable=True,
                    )
                    yield JobLogCompleteEvent(reason="unavailable")
                    return
                continue
            if current.terminal:
                ready = await self._ready_log_paths(paths)
                if not ready:
                    yield JobLogErrorEvent(
                        code="job_log_unavailable",
                        message="The job finished without creating a readable output file.",
                        retryable=False,
                    )
                    yield JobLogCompleteEvent(reason="unavailable")
                    return
                yield self._metadata_event(current, ready)
                yield JobLogStatusEvent(
                    status="finalizing",
                    message="Loading the final job output.",
                )
                snapshot_failed = False
                async for event in self._stream_log_snapshot(ready, sequence):
                    if isinstance(event, JobLogChunkEvent):
                        sequence = event.sequence
                    elif isinstance(event, JobLogErrorEvent):
                        snapshot_failed = True
                    yield event
                yield JobLogCompleteEvent(
                    reason="unavailable" if snapshot_failed else "job_finished"
                )
                return

        yield self._metadata_event(current, paths)
        yield JobLogStatusEvent(status="live", message="Following live job output.")
        async for event in self._follow_log_paths(paths, current, remote_user, sequence):
            yield event

    def _metadata_event(
        self,
        metadata: JobLogMetadata,
        paths: dict[str, str],
    ) -> JobLogMetadataEvent:
        return JobLogMetadataEvent(
            job_id=metadata.job_id,
            state=metadata.state,
            sources=cast(list[JobLogSource], list(paths)),
            initial_lines=_LOG_INITIAL_LINES,
        )

    async def _stream_log_snapshot(
        self,
        paths: dict[str, str],
        sequence: int,
    ) -> AsyncIterator[JobLogEvent]:
        for source, path in paths.items():
            command = build_tail_command(path, initial_lines=_LOG_INITIAL_LINES, follow=False)
            try:
                async with self._remote_stream(command) as stream:
                    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                    async for chunk in stream:
                        text = decoder.decode(chunk)
                        if text:
                            sequence += 1
                            yield JobLogChunkEvent(
                                source=cast(JobLogSource, source),
                                sequence=sequence,
                                text=text,
                            )
                    final_text = decoder.decode(b"", final=True)
                    if final_text:
                        sequence += 1
                        yield JobLogChunkEvent(
                            source=cast(JobLogSource, source),
                            sequence=sequence,
                            text=final_text,
                        )
            except (ClusterConnectionError, RemoteCommandError):
                yield JobLogErrorEvent(
                    code="job_log_stream_failed",
                    message="A remote log file could not be read.",
                    retryable=True,
                )

    async def _follow_log_paths(
        self,
        paths: dict[str, str],
        metadata: JobLogMetadata,
        remote_user: str,
        sequence: int,
    ) -> AsyncIterator[JobLogEvent]:
        queue: asyncio.Queue[tuple[str, str | None, object | None]] = asyncio.Queue(
            maxsize=_LOG_QUEUE_CHUNKS
        )

        async def read_source(source: str, stream: AsyncIterator[bytes]) -> None:
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            try:
                async for chunk in stream:
                    text = decoder.decode(chunk)
                    if text:
                        await queue.put(("chunk", source, text))
                final_text = decoder.decode(b"", final=True)
                if final_text:
                    await queue.put(("chunk", source, final_text))
                await queue.put(("done", source, None))
            except Exception as exc:
                await queue.put(("reader_error", source, exc))

        async def poll_state() -> None:
            failures = 0
            while True:
                await asyncio.sleep(_LOG_STATUS_POLL_SECONDS)
                try:
                    latest = await self._resolve_job_log_metadata(metadata.job_id, remote_user)
                    failures = 0
                except Exception:
                    failures += 1
                    if failures >= _LOG_MAX_POLL_FAILURES:
                        await queue.put(("poll_error", None, None))
                        return
                    continue
                if latest.terminal:
                    await queue.put(("terminal", None, None))
                    return

        reader_tasks: list[asyncio.Task[None]] = []
        poll_task: asyncio.Task[None] | None = None
        async with AsyncExitStack() as stack:
            try:
                for source, path in paths.items():
                    command = build_tail_command(
                        path,
                        initial_lines=_LOG_INITIAL_LINES,
                        follow=True,
                    )
                    stream = await stack.enter_async_context(self._remote_stream(command))
                    reader_tasks.append(asyncio.create_task(read_source(source, stream)))
                poll_task = asyncio.create_task(poll_state())
                done_sources: set[str] = set()
                while True:
                    kind, queue_source, payload = await queue.get()
                    if kind == "chunk":
                        sequence += 1
                        yield JobLogChunkEvent(
                            source=cast(JobLogSource, queue_source),
                            sequence=sequence,
                            text=cast(str, payload),
                        )
                        continue
                    if kind == "done" and queue_source is not None:
                        done_sources.add(queue_source)
                        if len(done_sources) < len(paths):
                            continue
                    if kind == "terminal":
                        yield JobLogStatusEvent(
                            status="finalizing",
                            message="The job finished; collecting final output.",
                        )
                        deadline = asyncio.get_running_loop().time() + _LOG_FINAL_DRAIN_SECONDS
                        while True:
                            remaining = deadline - asyncio.get_running_loop().time()
                            if remaining <= 0:
                                break
                            try:
                                queued_kind, queued_source, queued_payload = await asyncio.wait_for(
                                    queue.get(), timeout=remaining
                                )
                            except TimeoutError:
                                break
                            if queued_kind == "chunk":
                                sequence += 1
                                yield JobLogChunkEvent(
                                    source=cast(JobLogSource, queued_source),
                                    sequence=sequence,
                                    text=cast(str, queued_payload),
                                )
                        yield JobLogCompleteEvent(reason="job_finished")
                        return
                    code = (
                        "job_log_metadata_unavailable"
                        if kind == "poll_error"
                        else "job_log_stream_failed"
                    )
                    yield JobLogErrorEvent(
                        code=code,
                        message="The live log connection ended unexpectedly.",
                        retryable=True,
                    )
                    yield JobLogCompleteEvent(reason="unavailable")
                    return
            finally:
                tasks = [*reader_tasks, *([poll_task] if poll_task is not None else [])]
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    with suppress(asyncio.CancelledError):
                        await asyncio.gather(*tasks, return_exceptions=True)

    async def _ready_log_paths(self, paths: dict[str, str]) -> dict[str, str]:
        ready: dict[str, str] = {}
        for source, path in paths.items():
            if (
                await self._remote_file_test(path, "exists")
                and await self._remote_file_test(path, "regular")
                and await self._remote_file_test(path, "readable")
            ):
                ready[source] = path
        return ready

    async def _remote_file_test(self, path: str, predicate: str) -> bool:
        try:
            await self._execute(build_file_test_command(path, predicate))
        except RemoteCommandError:
            return False
        return True

    def _remote_stream(self, command: SlurmCommand) -> AbstractAsyncContextManager[Any]:
        stream_method = getattr(self._executor, "stream", None)
        if not callable(stream_method):
            raise ValueError("The configured SSH executor does not support streaming.")
        return cast(
            AbstractAsyncContextManager[Any],
            stream_method(
                command.executable,
                command.arguments,
                command_type=command.command_type,
            ),
        )

    async def _load_partitions(self, capabilities: SlurmCapabilities) -> list[Partition]:
        summaries: list[Partition]
        if capabilities.sinfo_json:
            try:
                summaries = parse_partitions_json(
                    await self._execute(build_partitions_json_command())
                )
            except (RemoteCommandError, SlurmJsonParseError):
                logger.info(
                    "slurm_json_fallback cluster_id=%s command_type=sinfo_partitions_json",
                    self._config.id,
                )
                summaries = parse_partitions_text(
                    await self._execute(build_partitions_text_command())
                )
        else:
            summaries = parse_partitions_text(await self._execute(build_partitions_text_command()))

        if capabilities.sinfo_json:
            try:
                details = parse_partitions_json(
                    await self._execute(build_scontrol_partitions_json_command())
                )
                return overlay_partition_details(summaries, details)
            except (RemoteCommandError, SlurmJsonParseError):
                logger.info(
                    "slurm_partition_details_unavailable cluster_id=%s",
                    self._config.id,
                )
        return summaries

    async def _load_nodes(self, capabilities: SlurmCapabilities) -> list[Node]:
        if capabilities.sinfo_json:
            try:
                return parse_nodes_json(await self._execute(build_scontrol_nodes_json_command()))
            except (RemoteCommandError, SlurmJsonParseError):
                logger.info(
                    "slurm_json_fallback cluster_id=%s command_type=scontrol_nodes_json",
                    self._config.id,
                )
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

    def _require_file_browsing(self) -> None:
        if not self._config.allow_file_browsing:
            raise FileBrowsingDisabledError(self._config.id)

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
