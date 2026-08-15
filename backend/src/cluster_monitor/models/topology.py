"""Normalized cluster topology models."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from cluster_monitor.models.base import ApiModel
from cluster_monitor.models.node import Node, Partition


class TopologyKind(StrEnum):
    FLAT = "flat"
    TREE = "tree"
    BLOCK = "block"
    RING = "ring"
    UNKNOWN = "unknown"


class TopologyGroupKind(StrEnum):
    SWITCH = "switch"
    BLOCK = "block"
    RING = "ring"


class TopologyGroup(ApiModel):
    id: str
    name: str
    kind: TopologyGroupKind
    child_group_ids: list[str] = Field(default_factory=list)
    node_names: list[str] = Field(default_factory=list)
    link_speed: str | None = None


class ClusterTopology(ApiModel):
    cluster_id: str
    kind: TopologyKind
    partitions: list[Partition]
    nodes: list[Node]
    groups: list[TopologyGroup] = Field(default_factory=list)
    captured_at: datetime
