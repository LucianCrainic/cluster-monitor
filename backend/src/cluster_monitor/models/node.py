"""Normalized Slurm node and partition API models."""

from enum import StrEnum

from pydantic import Field

from cluster_monitor.models.base import ApiModel


class NodeState(StrEnum):
    IDLE = "idle"
    ALLOCATED = "allocated"
    MIXED = "mixed"
    DRAINED = "drained"
    DOWN = "down"
    COMPLETING = "completing"
    UNKNOWN = "unknown"


class Partition(ApiModel):
    name: str
    availability: bool
    state: str
    time_limit: str | None = None
    node_count: int = Field(ge=0)
    allocated_node_count: int = Field(ge=0)
    idle_node_count: int = Field(ge=0)
    other_node_count: int = Field(ge=0)
    is_default: bool = False
    node_names: list[str] = Field(default_factory=list)
    qos: list[str] = Field(default_factory=list)
    minimum_nodes: int | None = Field(default=None, ge=0)
    maximum_nodes: int | None = Field(default=None, ge=0)
    maximum_cpus_per_node: int | None = Field(default=None, ge=0)
    default_memory_mb_per_node: int | None = Field(default=None, ge=0)
    default_memory_mb_per_cpu: int | None = Field(default=None, ge=0)
    maximum_time_minutes: int | None = Field(default=None, ge=0)


class Node(ApiModel):
    name: str
    partition_names: list[str] = Field(default_factory=list)
    state: NodeState
    state_raw: str
    cpu_count: int = Field(ge=0)
    allocated_cpus: int = Field(ge=0)
    memory_mb: int = Field(ge=0)
    allocated_memory_mb: int | None = Field(default=None, ge=0)
    free_memory_mb: int | None = Field(default=None, ge=0)
    cpu_load: float | None = Field(default=None, ge=0)
    sockets: int | None = Field(default=None, ge=0)
    cores_per_socket: int | None = Field(default=None, ge=0)
    threads_per_core: int | None = Field(default=None, ge=0)
    configured_features: list[str] = Field(default_factory=list)
    active_features: list[str] = Field(default_factory=list)
    generic_resources: list[str] = Field(default_factory=list)
    allocated_generic_resources: list[str] = Field(default_factory=list)
    gpu_resources: list[str] = Field(default_factory=list)
    reason: str | None = None
