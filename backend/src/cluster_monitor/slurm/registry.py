"""Configured backend registry."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from cluster_monitor.config import ClusterConfig, MonitorConfig
from cluster_monitor.exceptions import ClusterNotFoundError
from cluster_monitor.logging import get_logger
from cluster_monitor.models import BackendType, Cluster, ConnectionStatus
from cluster_monitor.slurm.backend import SlurmBackend
from cluster_monitor.slurm.mock import MockSlurmBackend
from cluster_monitor.slurm.ssh_backend import SshSlurmBackend

logger = get_logger("slurm.registry")

BackendFactory = Callable[[ClusterConfig], SlurmBackend]


class BackendRegistry:
    """Owns one backend implementation per configured cluster."""

    def __init__(
        self,
        config: MonitorConfig,
        *,
        factories: dict[BackendType, BackendFactory] | None = None,
    ) -> None:
        default_factories: dict[BackendType, BackendFactory] = {
            BackendType.MOCK: MockSlurmBackend,
            BackendType.SSH: SshSlurmBackend,
        }
        selected_factories = default_factories if factories is None else factories
        self._cluster_order = [cluster.id for cluster in config.clusters]
        self._configs = {cluster.id: cluster for cluster in config.clusters}
        self._backends = {
            cluster.id: selected_factories[cluster.backend](cluster) for cluster in config.clusters
        }

    def get(self, cluster_id: str) -> SlurmBackend:
        try:
            return self._backends[cluster_id]
        except KeyError as exc:
            raise ClusterNotFoundError(cluster_id) from exc

    async def list_clusters(self) -> list[Cluster]:
        return list(
            await asyncio.gather(
                *(self._safe_cluster(cluster_id) for cluster_id in self._cluster_order)
            )
        )

    async def _safe_cluster(self, cluster_id: str) -> Cluster:
        try:
            return await self._backends[cluster_id].get_cluster()
        except Exception:
            config = self._configs[cluster_id]
            logger.exception("cluster_metadata_failure cluster_id=%s", cluster_id)
            return Cluster(
                id=config.id,
                name=config.name,
                backend=config.backend,
                connection_status=ConnectionStatus.UNAVAILABLE,
                job_actions_enabled=config.allow_job_actions,
                file_browser_enabled=config.allow_file_browsing,
                last_error="Cluster metadata could not be loaded.",
            )
