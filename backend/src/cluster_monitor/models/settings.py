"""Frontend-safe application settings models."""

from pydantic import Field

from cluster_monitor.models.base import ApiModel


class RefreshSettings(ApiModel):
    overview_seconds: int = Field(default=10, ge=1, le=3600)
    jobs_seconds: int = Field(default=10, ge=1, le=3600)
    nodes_seconds: int = Field(default=30, ge=1, le=3600)
    partitions_seconds: int = Field(default=30, ge=1, le=3600)
    history_seconds: int = Field(default=60, ge=1, le=3600)


class ClientSettings(ApiModel):
    refresh: RefreshSettings
    default_cluster_id: str
