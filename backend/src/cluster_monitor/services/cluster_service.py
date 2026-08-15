"""Application service that keeps API concerns out of Slurm backends."""

from __future__ import annotations

from cluster_monitor.config import MonitorConfig
from cluster_monitor.models import (
    ClientSettings,
    Cluster,
    ClusterOverview,
    ClusterTopology,
    Job,
    JobCancellationReceipt,
    JobDetails,
    JobLogSession,
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
from cluster_monitor.slurm import BackendRegistry


class ClusterService:
    """Cluster orchestration, filtering, and explicitly requested mutations."""

    def __init__(self, config: MonitorConfig, registry: BackendRegistry) -> None:
        self._config = config
        self._registry = registry

    async def list_clusters(self) -> list[Cluster]:
        return await self._registry.list_clusters()

    async def get_cluster(self, cluster_id: str) -> Cluster:
        return await self._registry.get(cluster_id).get_cluster()

    async def get_overview(self, cluster_id: str) -> ClusterOverview:
        return await self._registry.get(cluster_id).get_overview()

    async def get_partitions(self, cluster_id: str) -> list[Partition]:
        return await self._registry.get(cluster_id).get_partitions()

    async def get_nodes(
        self,
        cluster_id: str,
        *,
        state: NodeState | None = None,
        partition: str | None = None,
    ) -> list[Node]:
        nodes = await self._registry.get(cluster_id).get_nodes()
        if state is not None:
            nodes = [node for node in nodes if node.state is state]
        if partition is not None:
            nodes = [node for node in nodes if partition in node.partition_names]
        return nodes

    async def get_topology(self, cluster_id: str) -> ClusterTopology:
        return await self._registry.get(cluster_id).get_topology()

    async def list_remote_directory(
        self,
        cluster_id: str,
        request: RemoteDirectoryRequest,
    ) -> RemoteDirectory:
        return await self._registry.get(cluster_id).list_remote_directory(request)

    async def preview_remote_file(
        self,
        cluster_id: str,
        request: RemoteFilePreviewRequest,
    ) -> RemoteFilePreview:
        return await self._registry.get(cluster_id).preview_remote_file(request)

    async def get_jobs(
        self,
        cluster_id: str,
        *,
        user: str | None = None,
        state: JobState | None = None,
        partition: str | None = None,
        limit: int = 100,
    ) -> list[Job]:
        jobs = await self._registry.get(cluster_id).get_jobs(user)
        return self._filter_jobs(jobs, state=state, partition=partition)[:limit]

    async def get_job(self, cluster_id: str, job_id: str) -> JobDetails:
        return await self._registry.get(cluster_id).get_job(job_id)

    async def open_job_log_stream(self, cluster_id: str, job_id: str) -> JobLogSession:
        return await self._registry.get(cluster_id).open_job_log_stream(job_id)

    async def get_recent_jobs(
        self,
        cluster_id: str,
        *,
        user: str | None = None,
        state: JobState | None = None,
        partition: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        jobs = await self._registry.get(cluster_id).get_recent_jobs(user, limit=500)
        return self._filter_jobs(jobs, state=state, partition=partition)[:limit]

    async def submit_job(
        self,
        cluster_id: str,
        request: JobSubmissionRequest,
    ) -> JobSubmissionReceipt:
        return await self._registry.get(cluster_id).submit_job(request)

    async def cancel_job(self, cluster_id: str, job_id: str) -> JobCancellationReceipt:
        return await self._registry.get(cluster_id).cancel_job(job_id)

    def get_client_settings(self) -> ClientSettings:
        return ClientSettings(
            refresh=self._config.application.refresh,
            default_cluster_id=self._config.clusters[0].id,
        )

    @staticmethod
    def _filter_jobs(
        jobs: list[Job],
        *,
        state: JobState | None,
        partition: str | None,
    ) -> list[Job]:
        if state is not None:
            jobs = [job for job in jobs if job.state is state]
        if partition is not None:
            jobs = [job for job in jobs if job.partition == partition]
        return jobs
