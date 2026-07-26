"""Backend interface consumed by the service layer."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cluster_monitor.models import (
    Cluster,
    ClusterOverview,
    Job,
    JobCancellationReceipt,
    JobDetails,
    JobSubmissionReceipt,
    JobSubmissionRequest,
    Node,
    Partition,
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

    async def get_jobs(self, user: str | None = None) -> list[Job]:
        """Return active jobs for the selected or configured user."""
        ...

    async def get_job(self, job_id: str) -> JobDetails:
        """Return details for one active or recent job."""
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
