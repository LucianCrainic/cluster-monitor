"""Backend interface consumed by the service layer."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cluster_monitor.models import (
    Cluster,
    ClusterOverview,
    ClusterTopology,
    Job,
    JobCancellationReceipt,
    JobDetails,
    JobLogSession,
    JobSubmissionReceipt,
    JobSubmissionRequest,
    Node,
    Partition,
    RemoteDirectory,
    RemoteDirectoryRequest,
    RemoteFilePreview,
    RemoteFilePreviewRequest,
)


@runtime_checkable
class SlurmBackend(Protocol):
    """Monitoring and explicitly confirmed job operations."""

    async def get_cluster(self) -> Cluster:
        """Return connection metadata without fetching a full data set."""
        ...

    async def get_overview(self) -> ClusterOverview:
        """Return a compact cluster summary."""
        ...

    async def get_partitions(self) -> list[Partition]:
        """Return normalized partition data."""
        ...

    async def get_nodes(self) -> list[Node]:
        """Return normalized node data."""
        ...

    async def get_topology(self) -> ClusterTopology:
        """Return one coherent resource and optional physical-topology snapshot."""
        ...

    async def list_remote_directory(self, request: RemoteDirectoryRequest) -> RemoteDirectory:
        """List one SSH-visible directory without changing remote state."""
        ...

    async def preview_remote_file(self, request: RemoteFilePreviewRequest) -> RemoteFilePreview:
        """Preview one bounded UTF-8 regular file without changing remote state."""
        ...

    async def get_jobs(self, user: str | None = None) -> list[Job]:
        """Return active jobs for the selected or configured user."""
        ...

    async def get_job(self, job_id: str) -> JobDetails:
        """Return details for one active or recent job."""
        ...

    async def open_job_log_stream(self, job_id: str) -> JobLogSession:
        """Preflight and open one read-only stream of job-log events."""
        ...

    async def get_recent_jobs(
        self,
        user: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        """Return recently completed jobs."""
        ...

    async def submit_job(self, request: JobSubmissionRequest) -> JobSubmissionReceipt:
        """Submit one validated script and return its scheduler-assigned ID."""
        ...

    async def cancel_job(self, job_id: str) -> JobCancellationReceipt:
        """Cancel one active job owned by the configured Slurm user."""
        ...
