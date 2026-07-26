"""Hermetic unavailable SSH backend used by API tests and offline demos."""

from __future__ import annotations

from cluster_monitor.config import ClusterConfig
from cluster_monitor.exceptions import ClusterUnavailableError
from cluster_monitor.models import (
    BackendType,
    Cluster,
    ClusterOverview,
    ConnectionStatus,
    Job,
    JobCancellationReceipt,
    JobDetails,
    JobSubmissionReceipt,
    JobSubmissionRequest,
    Node,
    Partition,
)


class UnavailableSshSlurmBackend:
    """SSH-shaped test double that never opens a connection."""

    _MESSAGE = (
        "SSH monitoring is unavailable in this test configuration. "
        "Select the mock cluster or configure a real OpenSSH alias."
    )

    def __init__(self, config: ClusterConfig) -> None:
        self._config = config

    def _unavailable(self) -> ClusterUnavailableError:
        return ClusterUnavailableError(self._config.id, self._MESSAGE)

    async def get_cluster(self) -> Cluster:
        return Cluster(
            id=self._config.id,
            name=self._config.name,
            backend=BackendType.SSH,
            connection_status=ConnectionStatus.UNAVAILABLE,
            job_actions_enabled=self._config.allow_job_actions,
            last_error=self._MESSAGE,
        )

    async def get_overview(self) -> ClusterOverview:
        raise self._unavailable()

    async def get_partitions(self) -> list[Partition]:
        raise self._unavailable()

    async def get_nodes(self) -> list[Node]:
        raise self._unavailable()

    async def get_jobs(self, user: str | None = None) -> list[Job]:
        del user
        raise self._unavailable()

    async def get_job(self, job_id: str) -> JobDetails:
        del job_id
        raise self._unavailable()

    async def get_recent_jobs(
        self,
        user: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        del user, limit
        raise self._unavailable()

    async def submit_job(self, request: JobSubmissionRequest) -> JobSubmissionReceipt:
        del request
        raise self._unavailable()

    async def cancel_job(self, job_id: str) -> JobCancellationReceipt:
        del job_id
        raise self._unavailable()
