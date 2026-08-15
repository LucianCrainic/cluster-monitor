"""Parsing and assembly for optional Slurm physical topology data."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime

from cluster_monitor.models import (
    ClusterTopology,
    Node,
    Partition,
    TopologyGroup,
    TopologyGroupKind,
    TopologyKind,
)

_FIELD = re.compile(r"(?:^|\s)(?P<key>[A-Za-z][A-Za-z0-9_]*)=")
_BRACKET = re.compile(r"^(?P<prefix>[^\[]*)\[(?P<body>[^\]]+)\](?P<suffix>.*)$")


class SlurmTopologyParseError(ValueError):
    """Slurm topology output could not be normalized safely."""


def parse_topology_text(output: str) -> tuple[TopologyKind, list[TopologyGroup]]:
    groups: list[TopologyGroup] = []
    detected: TopologyKind | None = None
    for line in output.splitlines():
        fields = _fields(line.strip())
        if not fields:
            continue
        if name := fields.get("SwitchName"):
            kind = TopologyKind.TREE
            group_kind = TopologyGroupKind.SWITCH
            identifier = f"switch:{name}"
            children = [f"switch:{child}" for child in _split_expression(fields.get("Switches"))]
        elif name := fields.get("BlockName"):
            kind = TopologyKind.BLOCK
            group_kind = TopologyGroupKind.BLOCK
            identifier = f"block:{name}"
            children = []
        elif name := fields.get("RingName"):
            kind = TopologyKind.RING
            group_kind = TopologyGroupKind.RING
            identifier = f"ring:{name}"
            children = []
        else:
            continue
        if detected is not None and detected is not kind:
            raise SlurmTopologyParseError("Slurm returned mixed topology kinds.")
        detected = kind
        groups.append(
            TopologyGroup(
                id=identifier,
                name=name,
                kind=group_kind,
                child_group_ids=children,
                node_names=expand_slurm_hostlist(fields.get("Nodes")),
                link_speed=fields.get("LinkSpeed"),
            )
        )
    return detected or TopologyKind.FLAT, groups


def build_cluster_topology(
    cluster_id: str,
    partitions: Sequence[Partition],
    nodes: Sequence[Node],
    physical: tuple[TopologyKind, list[TopologyGroup]],
    captured_at: datetime,
) -> ClusterTopology:
    nodes_by_partition: dict[str, list[str]] = {}
    for node in nodes:
        for partition_name in node.partition_names:
            nodes_by_partition.setdefault(partition_name, []).append(node.name)

    enriched_partitions = [
        partition.model_copy(
            update={
                "node_names": sorted(
                    set(partition.node_names or nodes_by_partition.get(partition.name, []))
                )
            }
        )
        for partition in partitions
    ]
    kind, groups = physical
    known_nodes = {node.name for node in nodes}
    safe_groups = [
        group.model_copy(
            update={"node_names": [name for name in group.node_names if name in known_nodes]}
        )
        for group in groups
    ]
    return ClusterTopology(
        cluster_id=cluster_id,
        kind=kind,
        partitions=enriched_partitions,
        nodes=list(nodes),
        groups=safe_groups,
        captured_at=captured_at,
    )


def overlay_partition_details(
    summaries: Sequence[Partition],
    details: Sequence[Partition],
) -> list[Partition]:
    detail_by_name = {partition.name: partition for partition in details}
    merged: list[Partition] = []
    for summary in summaries:
        detail = detail_by_name.get(summary.name)
        if detail is None:
            merged.append(summary)
            continue
        merged.append(
            detail.model_copy(
                update={
                    "availability": summary.availability,
                    "state": summary.state,
                    "time_limit": summary.time_limit or detail.time_limit,
                    "node_count": summary.node_count or detail.node_count,
                    "allocated_node_count": summary.allocated_node_count,
                    "idle_node_count": summary.idle_node_count,
                    "other_node_count": summary.other_node_count,
                    "is_default": summary.is_default or detail.is_default,
                }
            )
        )
    known = {partition.name for partition in summaries}
    merged.extend(partition for partition in details if partition.name not in known)
    return merged


def _fields(line: str) -> dict[str, str]:
    matches = list(_FIELD.finditer(line))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        value = line[start:end].strip()
        if value and value.casefold() not in {"none", "(null)", "n/a"}:
            fields[match.group("key")] = value
    return fields


def _split_expression(value: str | None) -> list[str]:
    if not value:
        return []
    parts: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(value):
        if character == "[":
            depth += 1
        elif character == "]":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return [part.strip() for part in parts if part.strip()]


def expand_slurm_hostlist(value: str | None) -> list[str]:
    expanded: list[str] = []
    for expression in _split_expression(value):
        match = _BRACKET.fullmatch(expression)
        if match is None:
            expanded.append(expression)
            continue
        prefix = match.group("prefix")
        suffix = match.group("suffix")
        for component in match.group("body").split(","):
            bounds = component.split("-", maxsplit=1)
            if len(bounds) == 1 or not all(bound.isdigit() for bound in bounds):
                expanded.append(f"{prefix}{component}{suffix}")
                continue
            start, end = (int(bound) for bound in bounds)
            if end < start or end - start > 100_000:
                raise SlurmTopologyParseError("Slurm returned an invalid node range.")
            width = max(len(bounds[0]), len(bounds[1]))
            expanded.extend(
                f"{prefix}{number:0{width}d}{suffix}" for number in range(start, end + 1)
            )
    return list(dict.fromkeys(expanded))
