"""Validated job mutation requests and receipts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from cluster_monitor.models.base import ApiModel

_JOB_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PARTITION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


class JobSubmissionRequest(ApiModel):
    """A bounded sbatch script and its scheduler resource request."""

    job_name: str
    script: str = Field(min_length=2, max_length=131_072)
    partition: str | None = None
    nodes: int = Field(default=1, ge=1, le=128)
    cpus_per_task: int = Field(default=1, ge=1, le=1024)
    memory_mb: int | None = Field(default=None, ge=1, le=16_777_216)
    time_limit_minutes: int = Field(default=10, ge=1, le=525_600)
    gpus_per_node: int = Field(default=0, ge=0, le=64)

    @field_validator("job_name")
    @classmethod
    def valid_job_name(cls, value: str) -> str:
        if not _JOB_NAME.fullmatch(value):
            raise ValueError(
                "job_name must start with a letter or digit and contain only "
                "letters, digits, dots, underscores, or hyphens"
            )
        return value

    @field_validator("partition")
    @classmethod
    def valid_partition(cls, value: str | None) -> str | None:
        if value is not None and not _PARTITION_NAME.fullmatch(value):
            raise ValueError("partition must be a valid Slurm partition name")
        return value

    @field_validator("script")
    @classmethod
    def valid_script(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("script must not contain NUL bytes")
        if "\r" in value:
            raise ValueError("script must use Unix line endings")
        if not value.startswith("#!"):
            raise ValueError("script must start with a shebang such as #!/usr/bin/env bash")
        if any(line.lstrip().upper().startswith("#SBATCH") for line in value.splitlines()):
            raise ValueError(
                "script must not contain #SBATCH directives; use the reviewed resource fields"
            )
        if not value.endswith("\n"):
            value += "\n"
        return value


class JobSubmissionReceipt(ApiModel):
    cluster_id: str
    job_id: str
    submitted_at: datetime
    scheduler_cluster: str | None = None
    status: Literal["submitted"] = "submitted"


class JobCancellationReceipt(ApiModel):
    cluster_id: str
    job_id: str
    requested_at: datetime
    status: Literal["cancellation_requested"] = "cancellation_requested"
