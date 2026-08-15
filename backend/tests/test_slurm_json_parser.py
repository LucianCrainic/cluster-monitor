from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cluster_monitor.models import JobState, NodeState
from cluster_monitor.slurm.json_parser import (
    SlurmJsonParseError,
    parse_nodes_json,
    parse_partitions_json,
    parse_sacct_job_details_json,
    parse_sacct_jobs_json,
    parse_squeue_jobs_json,
)

FIXTURES = Path(__file__).parent / "fixtures" / "json"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parses_slurm_24_11_partition_shape() -> None:
    partitions = parse_partitions_json(_fixture("sinfo_24_11.json"))

    assert [partition.name for partition in partitions] == ["compute", "gpu"]
    assert partitions[0].availability is True
    assert partitions[0].state == "UP"
    assert partitions[0].time_limit == "2-00:00:00"
    assert (
        partitions[0].allocated_node_count,
        partitions[0].idle_node_count,
        partitions[0].other_node_count,
        partitions[0].node_count,
    ) == (1, 2, 1, 4)
    assert partitions[1].availability is False
    assert partitions[1].state == "DRAIN"
    assert partitions[1].time_limit == "UNLIMITED"
    assert partitions[1].node_count == 2


def test_parses_rich_scontrol_partition_and_node_fields() -> None:
    partitions = parse_partitions_json(
        json.dumps(
            {
                "partitions": [
                    {
                        "name": "students",
                        "partition": {"state": "UP", "default": True},
                        "nodes": {"configured": "node[123-124]", "total": 2},
                        "qos": "students_limit",
                        "minimums": {"nodes": 1},
                        "maximums": {
                            "nodes": 4,
                            "cpus_per_node": 62,
                            "time": {"number": 30, "set": True, "infinite": False},
                        },
                        "defaults": {"partition_memory_per_node": {"number": 1024, "set": True}},
                    }
                ]
            }
        )
    )
    nodes = parse_nodes_json(
        json.dumps(
            {
                "nodes": [
                    {
                        "name": "node124",
                        "partitions": ["students"],
                        "state": ["MIXED", "PLANNED"],
                        "cpus": 64,
                        "alloc_cpus": 32,
                        "real_memory": 257566,
                        "free_mem": 29257,
                        "cpu_load": 3150,
                        "sockets": 2,
                        "cores": 16,
                        "threads": 2,
                        "features": ["rtx6000"],
                        "active_features": ["rtx6000"],
                        "gres": "gpu:rtx6000:2",
                        "gres_used": "gpu:rtx6000:1",
                    }
                ]
            }
        )
    )

    partition = partitions[0]
    assert partition.is_default is True
    assert partition.node_names == ["node123", "node124"]
    assert partition.qos == ["students_limit"]
    assert partition.maximum_nodes == 4
    assert partition.maximum_cpus_per_node == 62
    assert partition.maximum_time_minutes == 30
    assert partition.default_memory_mb_per_node == 1024
    node = nodes[0]
    assert node.state is NodeState.MIXED
    assert node.free_memory_mb == 29257
    assert node.cpu_load == 31.5
    assert (node.sockets, node.cores_per_socket, node.threads_per_core) == (2, 16, 2)
    assert node.allocated_generic_resources == ["gpu:rtx6000:1"]


def test_parses_slurm_24_11_node_shape_and_wrapped_scalars() -> None:
    nodes = parse_nodes_json(_fixture("sinfo_24_11.json"))

    assert [node.name for node in nodes] == ["cpu001", "gpu001", "cpu003"]
    assert nodes[0].state is NodeState.IDLE
    assert nodes[0].allocated_memory_mb == 0

    gpu = nodes[1]
    assert gpu.partition_names == ["compute", "gpu"]
    assert gpu.state is NodeState.MIXED
    assert gpu.cpu_count == 64
    assert gpu.allocated_cpus == 32
    assert gpu.memory_mb == 524_288
    assert gpu.allocated_memory_mb == 262_144
    assert gpu.generic_resources == ["gpu:a100:4"]
    assert gpu.gpu_resources == ["gpu:a100:4"]

    drained = nodes[2]
    assert drained.state is NodeState.DRAINED
    assert drained.state_raw == "IDLE+DRAIN"
    assert drained.allocated_memory_mb is None
    assert drained.reason == "Scheduled hardware maintenance"


def test_parses_squeue_jobs_with_nested_and_direct_aliases() -> None:
    jobs = parse_squeue_jobs_json(_fixture("squeue_24_11.json"))

    assert [job.job_id for job in jobs] == ["12002", "12003_7"]
    running, pending = jobs
    assert running.state is JobState.RUNNING
    assert running.user == "researcher"
    assert running.nodes == 1
    assert running.node_list == ["gpu001"]
    assert running.requested_cpus == 8
    assert running.requested_memory_mb == 16_384
    assert running.requested_gpus == 2
    assert running.submit_time == datetime.fromtimestamp(1_768_467_600, tz=UTC)
    assert running.end_time is None
    assert running.elapsed_seconds == 3_600
    assert running.time_limit_seconds == 43_200
    assert running.reason is None

    assert pending.state is JobState.PENDING
    assert pending.reason == "Priority"
    assert pending.nodes == 2
    assert pending.node_list == []
    assert pending.requested_memory_mb == 8_192
    assert pending.requested_gpus == 0
    assert pending.time_limit_seconds == 3_600
    assert pending.array_job_id == "12003"
    assert pending.array_task_id == "7"


def test_preserves_numeric_array_and_heterogeneous_scope_from_squeue_json() -> None:
    array_job, heterogeneous_job = parse_squeue_jobs_json(_fixture("squeue_scoped_jobs_24_11.json"))

    assert array_job.job_id == "42000"
    assert array_job.array_job_id == "42000"
    assert array_job.array_task_id == "1-128%8"
    assert array_job.heterogeneous_job_id is None

    assert heterogeneous_job.job_id == "43000"
    assert heterogeneous_job.array_job_id is None
    assert heterogeneous_job.heterogeneous_job_id == "43000"
    assert heterogeneous_job.heterogeneous_job_offset == 0


def test_preserves_scope_in_sacct_job_details() -> None:
    output = _fixture("sacct_scoped_jobs_24_11.json")

    array_job = parse_sacct_job_details_json(output, "42000")
    heterogeneous_job = parse_sacct_job_details_json(output, "43000")

    assert array_job is not None
    assert array_job.array_job_id == "42000"
    assert array_job.array_task_id == "1-128%8"
    assert heterogeneous_job is not None
    assert heterogeneous_job.heterogeneous_job_id == "43000"
    assert heterogeneous_job.heterogeneous_job_offset == 0


def test_sacct_filters_steps_and_sorts_allocations_newest_first() -> None:
    jobs = parse_sacct_jobs_json(_fixture("sacct_24_11.json"))

    assert [job.job_id for job in jobs] == ["11998", "11997"]
    assert jobs[0].state is JobState.COMPLETED
    assert jobs[0].elapsed_seconds == 2_400
    assert jobs[0].time_limit_seconds == 7_200
    assert jobs[0].requested_cpus == 8
    assert jobs[0].requested_memory_mb == 16_384
    assert jobs[0].requested_gpus == 0
    assert jobs[1].state is JobState.FAILED
    assert jobs[1].reason == "NonZeroExitCode"


def test_sacct_job_details_merge_step_accounting() -> None:
    details = parse_sacct_job_details_json(
        _fixture("sacct_24_11.json"),
        "11998",
    )

    assert details is not None
    assert details.working_directory == "/home/researcher/work/preprocess"
    assert details.command == "/home/researcher/bin/preprocess"
    assert details.standard_output_path == "/home/researcher/logs/11998.out"
    assert details.standard_error_path == "/home/researcher/logs/11998.err"
    assert details.exit_code == "0:0"
    assert details.allocation_details == {
        "nodes": 1,
        "cpus": 8,
        "memory_mb": 16_384,
        "gpus": 0,
    }
    assert details.accounting is not None
    assert details.accounting.elapsed_cpu_seconds == 17_280
    assert details.accounting.max_rss_mb == 12_288
    assert details.accounting.consumed_energy_joules == 540_000


def test_sacct_missing_job_details_returns_none() -> None:
    assert (
        parse_sacct_job_details_json(
            _fixture("sacct_24_11.json"),
            "999999",
        )
        is None
    )


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (parse_partitions_json, {"sinfo": [], "errors": []}),
        (parse_nodes_json, {"nodes": {"nodes": []}, "errors": []}),
        (parse_squeue_jobs_json, {"jobs": [], "errors": []}),
        (parse_sacct_jobs_json, {"jobs": {"jobs": []}, "errors": []}),
        (parse_squeue_jobs_json, {}),
    ],
)
def test_empty_payload_shapes_return_empty_lists(
    parser: Callable[[str], Sequence[object]],
    payload: dict[str, object],
) -> None:
    assert parser(json.dumps(payload)) == []


def test_accepts_legacy_direct_sinfo_aliases() -> None:
    payload = {
        "partitions": [
            {
                "name": "short*",
                "availability": "up",
                "time_limit": "00:30:00",
                "node_count": 1,
                "allocated_nodes": 0,
                "idle_nodes": 1,
                "other_nodes": 0,
            }
        ],
        "nodes": [
            {
                "hostname": "short001",
                "partition_names": "short*",
                "state": "IDLE",
                "cpu_count": 16,
                "allocated_cpus": 0,
                "memory_mb": "64G",
                "allocated_memory_mb": "8G",
                "generic_resources": "gpu:t4:1",
            }
        ],
    }

    partitions = parse_partitions_json(json.dumps(payload))
    nodes = parse_nodes_json(json.dumps(payload))

    assert partitions[0].name == "short"
    assert partitions[0].time_limit == "00:30:00"
    assert nodes[0].name == "short001"
    assert nodes[0].partition_names == ["short"]
    assert nodes[0].memory_mb == 65_536
    assert nodes[0].allocated_memory_mb == 8_192
    assert nodes[0].gpu_resources == ["gpu:t4:1"]


@pytest.mark.parametrize(
    "bad_output",
    [
        "not-json SECRET-COMMAND",
        json.dumps(
            {
                "errors": [
                    {
                        "description": "PRIVATE /home/researcher/script.sh",
                    }
                ]
            }
        ),
    ],
)
def test_errors_are_sanitized_and_do_not_echo_output(bad_output: str) -> None:
    with pytest.raises(SlurmJsonParseError) as caught:
        parse_squeue_jobs_json(bad_output)

    rendered = str(caught.value)
    assert "SECRET-COMMAND" not in rendered
    assert "PRIVATE" not in rendered
    assert "/home/researcher" not in rendered


def test_invalid_record_uses_sanitized_parse_error() -> None:
    output = json.dumps(
        {
            "jobs": [
                {
                    "job_id": 1,
                    "name": "sensitive-job-name",
                }
            ]
        }
    )

    with pytest.raises(SlurmJsonParseError) as caught:
        parse_squeue_jobs_json(output)

    assert "sensitive-job-name" not in str(caught.value)
    assert caught.value.response_kind == "queue"
