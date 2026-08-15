from datetime import UTC, datetime

import pytest

from cluster_monitor.models import Node, NodeState, Partition, TopologyKind
from cluster_monitor.slurm.topology import (
    SlurmTopologyParseError,
    build_cluster_topology,
    parse_topology_text,
)


def test_tree_topology_expands_nodes_and_preserves_hierarchy() -> None:
    kind, groups = parse_topology_text(
        "SwitchName=leaf-a Nodes=node[001-002,010] LinkSpeed=100G\n"
        "SwitchName=core Switches=leaf-a\n"
    )

    assert kind is TopologyKind.TREE
    assert groups[0].node_names == ["node001", "node002", "node010"]
    assert groups[0].link_speed == "100G"
    assert groups[1].child_group_ids == ["switch:leaf-a"]


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("BlockName=b0 Nodes=node[1-2]\n", TopologyKind.BLOCK),
        ("RingName=r0 Nodes=node3\n", TopologyKind.RING),
        ("", TopologyKind.FLAT),
        ("No topology information available\n", TopologyKind.FLAT),
    ],
)
def test_topology_kinds_and_flat_fallback(output: str, expected: TopologyKind) -> None:
    kind, _ = parse_topology_text(output)

    assert kind is expected


def test_mixed_physical_topology_is_rejected() -> None:
    with pytest.raises(SlurmTopologyParseError):
        parse_topology_text("SwitchName=s0 Nodes=n1\nBlockName=b0 Nodes=n2\n")


def test_resource_snapshot_populates_partition_nodes_without_inference() -> None:
    partition = Partition(
        name="students",
        availability=True,
        state="UP",
        node_count=1,
        allocated_node_count=1,
        idle_node_count=0,
        other_node_count=0,
    )
    node = Node(
        name="node124",
        partition_names=["students"],
        state=NodeState.MIXED,
        state_raw="MIXED",
        cpu_count=64,
        allocated_cpus=32,
        memory_mb=257_566,
    )

    snapshot = build_cluster_topology(
        "crainic",
        [partition],
        [node],
        parse_topology_text(""),
        datetime(2026, 8, 14, tzinfo=UTC),
    )

    assert snapshot.kind is TopologyKind.FLAT
    assert snapshot.partitions[0].node_names == ["node124"]
    assert snapshot.groups == []
