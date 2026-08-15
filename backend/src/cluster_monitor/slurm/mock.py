"""Deterministic, fully local Slurm backend used by the MVP."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import PurePosixPath

from cluster_monitor.config import ClusterConfig
from cluster_monitor.exceptions import (
    FileBrowsingDisabledError,
    JobActionRejectedError,
    JobActionsDisabledError,
    JobNotFoundError,
    RemotePathInvalidError,
    RemotePathNotFoundError,
)
from cluster_monitor.models import (
    AccountingInfo,
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
    RemoteFileEntry,
    RemoteFileKind,
    RemoteFilePreview,
    RemoteFilePreviewRequest,
    RemotePreviewStatus,
    TopologyGroup,
    TopologyGroupKind,
    TopologyKind,
)
from cluster_monitor.slurm.remote_files import validate_remote_path

_MOCK_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
_MOCK_FILES: dict[str, str] = {
    "/home/student/project/job.sh": (
        '#!/bin/bash\n#SBATCH --job-name=demo\n\necho "Starting job"\nsrun hostname\n'
    ),
    "/home/student/project/config.yaml": "epochs: 12\nlearning_rate: 0.001\n",
    "/home/student/logs/11998.out": "Preprocessing complete\n",
    "/home/student/.profile": "export EDITOR=vim\n",
}
_MOCK_DIRECTORIES = {
    "/",
    "/home",
    "/home/student",
    "/home/student/project",
    "/home/student/logs",
}


class MockSlurmBackend:
    """Small deterministic cluster that never touches the network."""

    def __init__(self, config: ClusterConfig, *, delay_seconds: float = 0.01) -> None:
        self._config = config
        self._delay_seconds = delay_seconds
        self._user = "student" if config.slurm_user == "current" else config.slurm_user
        self._partitions = self._build_partitions()
        self._nodes = self._build_nodes()
        self._active_jobs = self._build_active_jobs()
        self._recent_jobs = self._build_recent_jobs()
        self._details = self._build_job_details()
        self._next_job_id = 13_000

    async def _delay(self) -> None:
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

    async def get_cluster(self) -> Cluster:
        await self._delay()
        return Cluster(
            id=self._config.id,
            name=self._config.name,
            backend=BackendType.MOCK,
            connection_status=ConnectionStatus.CONNECTED,
            job_actions_enabled=self._config.allow_job_actions,
            file_browser_enabled=self._config.allow_file_browsing,
            slurm_version="24.05.4-mock",
            last_successful_refresh=_MOCK_NOW,
        )

    async def get_overview(self) -> ClusterOverview:
        await self._delay()
        return ClusterOverview(
            cluster_id=self._config.id,
            connection_status=ConnectionStatus.CONNECTED,
            slurm_version="24.05.4-mock",
            total_nodes=len(self._nodes),
            idle_nodes=sum(node.state is NodeState.IDLE for node in self._nodes),
            allocated_nodes=sum(
                node.state in {NodeState.ALLOCATED, NodeState.MIXED} for node in self._nodes
            ),
            unavailable_nodes=sum(
                node.state in {NodeState.DRAINED, NodeState.DOWN} for node in self._nodes
            ),
            running_jobs=sum(job.state is JobState.RUNNING for job in self._active_jobs),
            pending_jobs=sum(job.state is JobState.PENDING for job in self._active_jobs),
            last_refresh=_MOCK_NOW,
        )

    async def get_partitions(self) -> list[Partition]:
        await self._delay()
        return [partition.model_copy(deep=True) for partition in self._partitions]

    async def get_nodes(self) -> list[Node]:
        await self._delay()
        return [node.model_copy(deep=True) for node in self._nodes]

    async def get_topology(self) -> ClusterTopology:
        await self._delay()
        return ClusterTopology(
            cluster_id=self._config.id,
            kind=TopologyKind.TREE,
            partitions=[partition.model_copy(deep=True) for partition in self._partitions],
            nodes=[node.model_copy(deep=True) for node in self._nodes],
            groups=[
                TopologyGroup(
                    id="switch:core",
                    name="core",
                    kind=TopologyGroupKind.SWITCH,
                    child_group_ids=["switch:cpu", "switch:gpu"],
                    node_names=[],
                ),
                TopologyGroup(
                    id="switch:cpu",
                    name="cpu",
                    kind=TopologyGroupKind.SWITCH,
                    node_names=["cpu001", "cpu002", "cpu003"],
                ),
                TopologyGroup(
                    id="switch:gpu",
                    name="gpu",
                    kind=TopologyGroupKind.SWITCH,
                    node_names=["gpu001"],
                ),
            ],
            captured_at=_MOCK_NOW,
        )

    async def list_remote_directory(
        self,
        request: RemoteDirectoryRequest,
    ) -> RemoteDirectory:
        await self._delay()
        self._require_file_browsing()
        validate_remote_path(request.path, self._config.id, allow_login_directory=True)
        path = request.path or "/home/student"
        if path not in _MOCK_DIRECTORIES:
            if path in _MOCK_FILES:
                raise RemotePathInvalidError(self._config.id, "The remote path is not a directory.")
            raise RemotePathNotFoundError(self._config.id)
        entries: list[RemoteFileEntry] = []
        for directory in _MOCK_DIRECTORIES:
            if directory == path or str(PurePosixPath(directory).parent) != path:
                continue
            entries.append(self._mock_entry(directory, RemoteFileKind.DIRECTORY))
        for file_path, content in _MOCK_FILES.items():
            if str(PurePosixPath(file_path).parent) != path:
                continue
            if not request.show_hidden and PurePosixPath(file_path).name.startswith("."):
                continue
            entries.append(self._mock_entry(file_path, RemoteFileKind.FILE, len(content.encode())))
        entries.sort(
            key=lambda entry: (entry.kind is not RemoteFileKind.DIRECTORY, entry.name.casefold())
        )
        return RemoteDirectory(
            cluster_id=self._config.id,
            path=path,
            parent_path=None if path == "/" else str(PurePosixPath(path).parent),
            entries=entries,
            truncated=False,
        )

    async def preview_remote_file(
        self,
        request: RemoteFilePreviewRequest,
    ) -> RemoteFilePreview:
        await self._delay()
        self._require_file_browsing()
        validate_remote_path(request.path, self._config.id, allow_login_directory=False)
        content = _MOCK_FILES.get(request.path)
        if content is None:
            if request.path in _MOCK_DIRECTORIES:
                return RemoteFilePreview(
                    cluster_id=self._config.id,
                    path=request.path,
                    name=PurePosixPath(request.path).name or "/",
                    kind=RemoteFileKind.DIRECTORY,
                    size_bytes=0,
                    modified_at=_MOCK_NOW,
                    permissions="drwxr-xr-x",
                    status=RemotePreviewStatus.SPECIAL,
                )
            raise RemotePathNotFoundError(self._config.id)
        suffix = PurePosixPath(request.path).suffix.casefold()
        language = {
            ".sh": "shell",
            ".yaml": "yaml",
            ".yml": "yaml",
        }.get(suffix, "text")
        return RemoteFilePreview(
            cluster_id=self._config.id,
            path=request.path,
            name=PurePosixPath(request.path).name,
            kind=RemoteFileKind.FILE,
            size_bytes=len(content.encode()),
            modified_at=_MOCK_NOW,
            permissions="-rw-r--r--",
            status=RemotePreviewStatus.AVAILABLE,
            content=content,
            language=language,
        )

    async def get_jobs(self, user: str | None = None) -> list[Job]:
        await self._delay()
        selected_user = self._user if user is None else user
        return [job.model_copy(deep=True) for job in self._active_jobs if job.user == selected_user]

    async def get_job(self, job_id: str) -> JobDetails:
        await self._delay()
        details = self._details.get(job_id)
        if details is None:
            raise JobNotFoundError(self._config.id, job_id)
        return details.model_copy(deep=True)

    async def open_job_log_stream(self, job_id: str) -> JobLogSession:
        details = await self.get_job(job_id)

        async def events() -> AsyncIterator[JobLogEvent]:
            combined = details.standard_output_path == details.standard_error_path
            sources: list[JobLogSource] = ["combined"] if combined else ["stdout", "stderr"]
            yield JobLogMetadataEvent(
                job_id=job_id,
                state=details.state,
                sources=sources,
                initial_lines=200,
            )
            if details.state is JobState.PENDING:
                yield JobLogStatusEvent(
                    status="waiting",
                    message="Waiting for Slurm to create the job output files.",
                )
                await self._delay()
            if details.state in {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}:
                yield JobLogStatusEvent(
                    status="finalizing",
                    message="Loading the final job output.",
                )
            else:
                yield JobLogStatusEvent(status="live", message="Following live job output.")
            if combined:
                yield JobLogChunkEvent(
                    source="combined",
                    sequence=1,
                    text=f"[{job_id}] mock combined job output\n",
                )
            else:
                yield JobLogChunkEvent(
                    source="stdout",
                    sequence=1,
                    text=f"[{job_id}] mock standard output\n",
                )
                yield JobLogChunkEvent(
                    source="stderr",
                    sequence=2,
                    text=f"[{job_id}] mock standard error\n",
                )
            terminal = details.state in {
                JobState.COMPLETED,
                JobState.FAILED,
                JobState.CANCELLED,
                JobState.TIMEOUT,
                JobState.OUT_OF_MEMORY,
            }
            yield JobLogCompleteEvent(reason="snapshot_complete" if terminal else "job_finished")

        return JobLogSession(events=events())

    async def get_recent_jobs(
        self,
        user: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        await self._delay()
        selected_user = self._user if user is None else user
        matches = [job for job in self._recent_jobs if job.user == selected_user]
        return [job.model_copy(deep=True) for job in matches[:limit]]

    async def submit_job(self, request: JobSubmissionRequest) -> JobSubmissionReceipt:
        await self._delay()
        self._require_job_actions()
        job_id = str(self._next_job_id)
        self._next_job_id += 1
        job = Job(
            job_id=job_id,
            job_name=request.job_name,
            user=self._user,
            partition=request.partition or "compute",
            state=JobState.PENDING,
            state_raw="PENDING",
            reason="Priority",
            nodes=request.nodes,
            requested_cpus=request.cpus_per_task,
            requested_memory_mb=request.memory_mb,
            requested_gpus=request.gpus_per_node * request.nodes,
            submit_time=_MOCK_NOW,
            elapsed_seconds=0,
            time_limit_seconds=request.time_limit_minutes * 60,
        )
        self._active_jobs.insert(0, job)
        self._details[job_id] = JobDetails(
            **job.model_dump(),
            allocation_details={
                "nodes": request.nodes,
                "cpus_per_task": request.cpus_per_task,
                "memory_mb": request.memory_mb,
                "gpus_per_node": request.gpus_per_node,
            },
        )
        return JobSubmissionReceipt(
            cluster_id=self._config.id,
            job_id=job_id,
            submitted_at=_MOCK_NOW,
        )

    async def cancel_job(self, job_id: str) -> JobCancellationReceipt:
        await self._delay()
        self._require_job_actions()
        match = next((job for job in self._active_jobs if job.job_id == job_id), None)
        if match is None:
            if job_id in self._details:
                raise JobActionRejectedError(self._config.id, "cancel", job_id=job_id)
            raise JobNotFoundError(self._config.id, job_id)

        self._active_jobs = [job for job in self._active_jobs if job.job_id != job_id]
        cancelled = match.model_copy(
            update={
                "state": JobState.CANCELLED,
                "state_raw": "CANCELLED",
                "reason": "CancelledByUser",
                "end_time": _MOCK_NOW,
            }
        )
        self._recent_jobs.insert(0, cancelled)
        previous_details = self._details[job_id]
        self._details[job_id] = previous_details.model_copy(
            update={
                "state": JobState.CANCELLED,
                "state_raw": "CANCELLED",
                "reason": "CancelledByUser",
                "end_time": _MOCK_NOW,
            }
        )
        return JobCancellationReceipt(
            cluster_id=self._config.id,
            job_id=job_id,
            requested_at=_MOCK_NOW,
        )

    def _require_job_actions(self) -> None:
        if not self._config.allow_job_actions:
            raise JobActionsDisabledError(self._config.id)

    def _require_file_browsing(self) -> None:
        if not self._config.allow_file_browsing:
            raise FileBrowsingDisabledError(self._config.id)

    @staticmethod
    def _mock_entry(
        path: str,
        kind: RemoteFileKind,
        size_bytes: int = 0,
    ) -> RemoteFileEntry:
        return RemoteFileEntry(
            name=PurePosixPath(path).name,
            path=path,
            kind=kind,
            size_bytes=size_bytes,
            modified_at=_MOCK_NOW,
            permissions="drwxr-xr-x" if kind is RemoteFileKind.DIRECTORY else "-rw-r--r--",
            readable=True,
        )

    @staticmethod
    def _build_partitions() -> list[Partition]:
        return [
            Partition(
                name="compute",
                availability=True,
                state="UP",
                time_limit="2-00:00:00",
                node_count=3,
                allocated_node_count=1,
                idle_node_count=1,
                other_node_count=1,
                is_default=True,
                node_names=["cpu001", "cpu002", "cpu003"],
                qos=["normal"],
                minimum_nodes=1,
                maximum_nodes=16,
                maximum_cpus_per_node=64,
                default_memory_mb_per_cpu=4_096,
                maximum_time_minutes=2_880,
            ),
            Partition(
                name="gpu",
                availability=True,
                state="UP",
                time_limit="1-00:00:00",
                node_count=1,
                allocated_node_count=1,
                idle_node_count=0,
                other_node_count=0,
                node_names=["gpu001"],
                qos=["gpu"],
                minimum_nodes=1,
                maximum_nodes=4,
                maximum_cpus_per_node=64,
                default_memory_mb_per_node=524_288,
                maximum_time_minutes=1_440,
            ),
        ]

    @staticmethod
    def _build_nodes() -> list[Node]:
        return [
            Node(
                name="cpu001",
                partition_names=["compute"],
                state=NodeState.IDLE,
                state_raw="IDLE",
                cpu_count=64,
                allocated_cpus=0,
                memory_mb=262_144,
                allocated_memory_mb=0,
                free_memory_mb=250_000,
                cpu_load=0.42,
                sockets=2,
                cores_per_socket=16,
                threads_per_core=2,
                configured_features=["zen4", "local-ssd"],
                active_features=["zen4", "local-ssd"],
            ),
            Node(
                name="cpu002",
                partition_names=["compute"],
                state=NodeState.ALLOCATED,
                state_raw="ALLOCATED",
                cpu_count=64,
                allocated_cpus=48,
                memory_mb=262_144,
                allocated_memory_mb=196_608,
                free_memory_mb=58_000,
                cpu_load=47.8,
                sockets=2,
                cores_per_socket=16,
                threads_per_core=2,
                configured_features=["zen4"],
                active_features=["zen4"],
            ),
            Node(
                name="cpu003",
                partition_names=["compute"],
                state=NodeState.DRAINED,
                state_raw="DRAINED",
                cpu_count=64,
                allocated_cpus=0,
                memory_mb=262_144,
                allocated_memory_mb=0,
                free_memory_mb=248_000,
                cpu_load=0.0,
                sockets=2,
                cores_per_socket=16,
                threads_per_core=2,
                reason="Scheduled hardware maintenance",
            ),
            Node(
                name="gpu001",
                partition_names=["gpu"],
                state=NodeState.MIXED,
                state_raw="MIXED",
                cpu_count=64,
                allocated_cpus=32,
                memory_mb=524_288,
                allocated_memory_mb=262_144,
                generic_resources=["gpu:a100:4"],
                gpu_resources=["A100 80GB x4"],
                allocated_generic_resources=["gpu:a100:2"],
                free_memory_mb=238_000,
                cpu_load=31.6,
                sockets=2,
                cores_per_socket=16,
                threads_per_core=2,
                configured_features=["a100", "nvlink"],
                active_features=["a100", "nvlink"],
            ),
        ]

    def _build_active_jobs(self) -> list[Job]:
        return [
            Job(
                job_id="12001",
                job_name="protein-sim",
                user=self._user,
                partition="compute",
                state=JobState.RUNNING,
                state_raw="RUNNING",
                nodes=1,
                node_list=["cpu002"],
                requested_cpus=48,
                requested_memory_mb=196_608,
                requested_gpus=0,
                submit_time=datetime(2026, 1, 15, 8, 55, tzinfo=UTC),
                start_time=datetime(2026, 1, 15, 9, 0, tzinfo=UTC),
                elapsed_seconds=10_800,
                time_limit_seconds=86_400,
            ),
            Job(
                job_id="12002",
                job_name="train-model",
                user=self._user,
                partition="gpu",
                state=JobState.RUNNING,
                state_raw="RUNNING",
                nodes=1,
                node_list=["gpu001"],
                requested_cpus=32,
                requested_memory_mb=262_144,
                requested_gpus=2,
                submit_time=datetime(2026, 1, 15, 9, 25, tzinfo=UTC),
                start_time=datetime(2026, 1, 15, 9, 30, tzinfo=UTC),
                elapsed_seconds=9_000,
                time_limit_seconds=43_200,
            ),
            Job(
                job_id="12003",
                job_name="gpu-sweep",
                user=self._user,
                partition="gpu",
                state=JobState.PENDING,
                state_raw="PENDING",
                reason="Resources",
                nodes=1,
                requested_cpus=16,
                requested_memory_mb=65_536,
                requested_gpus=4,
                submit_time=datetime(2026, 1, 15, 10, 45, tzinfo=UTC),
                elapsed_seconds=0,
                time_limit_seconds=21_600,
            ),
            Job(
                job_id="12004",
                job_name="parameter-scan",
                user=self._user,
                partition="compute",
                state=JobState.PENDING,
                state_raw="PENDING",
                reason="Priority",
                nodes=2,
                requested_cpus=64,
                requested_memory_mb=131_072,
                requested_gpus=0,
                submit_time=datetime(2026, 1, 15, 11, 15, tzinfo=UTC),
                elapsed_seconds=0,
                time_limit_seconds=28_800,
            ),
        ]

    def _build_recent_jobs(self) -> list[Job]:
        return [
            Job(
                job_id="11998",
                job_name="preprocess",
                user=self._user,
                partition="compute",
                state=JobState.COMPLETED,
                state_raw="COMPLETED",
                nodes=1,
                node_list=["cpu001"],
                requested_cpus=8,
                requested_memory_mb=16_384,
                requested_gpus=0,
                submit_time=datetime(2026, 1, 15, 7, 0, tzinfo=UTC),
                start_time=datetime(2026, 1, 15, 7, 2, tzinfo=UTC),
                end_time=datetime(2026, 1, 15, 7, 42, tzinfo=UTC),
                elapsed_seconds=2_400,
                time_limit_seconds=7_200,
            ),
            Job(
                job_id="11997",
                job_name="broken-run",
                user=self._user,
                partition="compute",
                state=JobState.FAILED,
                state_raw="FAILED",
                reason="NonZeroExitCode",
                nodes=1,
                node_list=["cpu002"],
                requested_cpus=4,
                requested_memory_mb=8_192,
                requested_gpus=0,
                submit_time=datetime(2026, 1, 15, 6, 30, tzinfo=UTC),
                start_time=datetime(2026, 1, 15, 6, 31, tzinfo=UTC),
                end_time=datetime(2026, 1, 15, 6, 33, tzinfo=UTC),
                elapsed_seconds=120,
                time_limit_seconds=3_600,
            ),
        ]

    def _build_job_details(self) -> dict[str, JobDetails]:
        jobs = [*self._active_jobs, *self._recent_jobs]
        details: dict[str, JobDetails] = {}
        for job in jobs:
            completed = job.state in {JobState.COMPLETED, JobState.FAILED}
            details[job.job_id] = JobDetails(
                **job.model_dump(),
                working_directory=f"/home/{self._user}/work/{job.job_name}",
                command=f"/home/{self._user}/bin/{job.job_name}",
                standard_output_path=f"/home/{self._user}/logs/{job.job_id}.out",
                standard_error_path=f"/home/{self._user}/logs/{job.job_id}.err",
                exit_code=(
                    "0:0"
                    if job.state is JobState.COMPLETED
                    else "1:0"
                    if job.state is JobState.FAILED
                    else None
                ),
                allocation_details={
                    "nodes": job.nodes,
                    "cpus": job.requested_cpus,
                    "memory_mb": job.requested_memory_mb,
                    "gpus": job.requested_gpus,
                },
                accounting=(
                    AccountingInfo(
                        elapsed_cpu_seconds=job.elapsed_seconds * max(job.requested_cpus, 1),
                        max_rss_mb=(
                            int(job.requested_memory_mb * 0.72)
                            if job.requested_memory_mb is not None
                            else None
                        ),
                        consumed_energy_joules=540_000,
                    )
                    if completed
                    else None
                ),
            )
        # Exercise the merged stdout/stderr path in the local demo.
        merged = details.get("12002")
        if merged is not None:
            details["12002"] = merged.model_copy(
                update={"standard_error_path": merged.standard_output_path}
            )
        return details
