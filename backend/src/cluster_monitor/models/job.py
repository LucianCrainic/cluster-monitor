"""Normalized Slurm job API models."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from cluster_monitor.models.base import ApiModel


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    OUT_OF_MEMORY = "out_of_memory"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class Job(ApiModel):
    job_id: str
    array_job_id: str | None = None
    array_task_id: str | None = None
    heterogeneous_job_id: str | None = None
    heterogeneous_job_offset: int | None = Field(default=None, ge=0)
    job_name: str
    user: str
    partition: str
    state: JobState
    state_raw: str
    reason: str | None = None
    nodes: int = Field(ge=0)
    node_list: list[str] = Field(default_factory=list)
    requested_cpus: int = Field(ge=0)
    requested_memory_mb: int | None = Field(default=None, ge=0)
    requested_gpus: int | None = Field(default=None, ge=0)
    submit_time: datetime | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    elapsed_seconds: int = Field(ge=0)
    time_limit_seconds: int | None = Field(default=None, ge=0)


class AccountingInfo(ApiModel):
    elapsed_cpu_seconds: int | None = Field(default=None, ge=0)
    max_rss_mb: int | None = Field(default=None, ge=0)
    consumed_energy_joules: int | None = Field(default=None, ge=0)


AllocationValue = str | int | float | bool | None


class JobDetails(Job):
    working_directory: str | None = None
    command: str | None = None
    standard_output_path: str | None = None
    standard_error_path: str | None = None
    exit_code: str | None = None
    allocation_details: dict[str, AllocationValue] = Field(default_factory=dict)
    accounting: AccountingInfo | None = None
