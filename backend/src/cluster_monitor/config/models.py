"""Validated YAML configuration models."""

from __future__ import annotations

import re

from pydantic import Field, field_validator, model_validator

from cluster_monitor.models import BackendType, RefreshSettings
from cluster_monitor.models.base import ApiModel

_CLUSTER_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_SSH_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_SLURM_USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")


class ApplicationConfig(ApiModel):
    bind_host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    refresh: RefreshSettings = Field(default_factory=RefreshSettings)

    @field_validator("bind_host")
    @classmethod
    def require_loopback(cls, value: str) -> str:
        if value not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("bind_host must be a loopback address")
        return value


class ClusterConfig(ApiModel):
    id: str
    name: str = Field(min_length=1, max_length=100)
    backend: BackendType
    ssh_host: str | None = None
    slurm_user: str = "current"
    command_timeout_seconds: float = Field(default=15.0, gt=0, le=300)
    allow_job_actions: bool = False
    allow_file_browsing: bool = False

    @field_validator("id")
    @classmethod
    def valid_cluster_id(cls, value: str) -> str:
        if not _CLUSTER_ID.fullmatch(value):
            raise ValueError(
                "cluster id must contain lowercase letters, digits, or internal hyphens"
            )
        return value

    @field_validator("ssh_host")
    @classmethod
    def valid_ssh_alias(cls, value: str | None) -> str | None:
        if value is not None and not _SSH_ALIAS.fullmatch(value):
            raise ValueError("ssh_host must be a valid OpenSSH host alias without whitespace")
        return value

    @field_validator("slurm_user")
    @classmethod
    def valid_slurm_user(cls, value: str) -> str:
        if value != "current" and not _SLURM_USER.fullmatch(value):
            raise ValueError("slurm_user must be 'current' or a valid account name")
        return value

    @model_validator(mode="after")
    def backend_has_required_fields(self) -> ClusterConfig:
        if self.backend is BackendType.SSH and not self.ssh_host:
            raise ValueError("ssh_host is required when backend is 'ssh'")
        if (
            self.backend is BackendType.SSH
            and self.allow_job_actions
            and self.slurm_user != "current"
        ):
            raise ValueError(
                "allow_job_actions requires slurm_user to be 'current' for SSH clusters"
            )
        return self


class MonitorConfig(ApiModel):
    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    clusters: list[ClusterConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def cluster_ids_are_unique(self) -> MonitorConfig:
        ids = [cluster.id for cluster in self.clusters]
        duplicates = sorted({cluster_id for cluster_id in ids if ids.count(cluster_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate cluster id(s): {', '.join(duplicates)}")
        return self
