"""Cluster and overview API models."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from cluster_monitor.models.base import ApiModel


class BackendType(StrEnum):
    MOCK = "mock"
    SSH = "ssh"


class ConnectionStatus(StrEnum):
    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class Cluster(ApiModel):
    id: str
    name: str
    backend: BackendType
    connection_status: ConnectionStatus
    job_actions_enabled: bool = False
    file_browser_enabled: bool = False
    slurm_version: str | None = None
    last_successful_refresh: datetime | None = None
    last_error: str | None = None


class ClusterOverview(ApiModel):
    cluster_id: str
    connection_status: ConnectionStatus
    slurm_version: str | None = None
    total_nodes: int = Field(ge=0)
    idle_nodes: int = Field(ge=0)
    allocated_nodes: int = Field(ge=0)
    unavailable_nodes: int = Field(ge=0)
    running_jobs: int = Field(ge=0)
    pending_jobs: int = Field(ge=0)
    last_refresh: datetime | None = None
    last_error: str | None = None
