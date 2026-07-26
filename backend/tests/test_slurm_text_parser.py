from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from cluster_monitor.models import JobState, NodeState
from cluster_monitor.slurm.text_parser import (
    NODE_SINFO_FORMAT,
    PARTITION_SINFO_FORMAT,
    SACCT_JOB_FIELDS,
    SQUEUE_JOB_FORMAT,
    SlurmTextParseError,
    parse_nodes_text,
    parse_partitions_text,
    parse_sacct_jobs_text,
    parse_slurm_duration,
    parse_slurm_gpu_count,
    parse_slurm_memory_mb,
    parse_slurm_node_list,
    parse_slurm_resource_list,
    parse_slurm_timestamp,
    parse_squeue_jobs_text,
)

FIXTURES = Path(__file__).parent / "fixtures" / "text"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_fixed_formats_are_explicit_and_machine_readable() -> None:
    assert PARTITION_SINFO_FORMAT == "%P|%a|%l|%D|%F"
    assert NODE_SINFO_FORMAT == "%N|%P|%T|%c|%C|%m|%e|%G|%E"
    assert SQUEUE_JOB_FORMAT == (
        "JobID:1|,ArrayJobID:1|,ArrayTaskID:1|,HetJobID:1|,HetJobOffset:1|,"
        "Name:1|,UserName:1|,Partition:1|,State:1|,"
        "NumNodes:1|,NodeList:1|,NumCPUs:1|,MinMemory:1|,tres-alloc:1|,"
        "SubmitTime:1|,StartTime:1|,TimeUsed:1|,TimeLimit:1|,Reason:1"
    )
    assert SACCT_JOB_FIELDS == (
        "JobIDRaw",
        "JobID",
        "JobName",
        "User",
        "Partition",
        "State",
        "NNodes",
        "NodeList",
        "ReqCPUS",
        "ReqMem",
        "ReqTRES",
        "Submit",
        "Start",
        "End",
        "Elapsed",
        "Timelimit",
        "Reason",
    )


def test_parses_partition_fixture() -> None:
    partitions = parse_partitions_text(_fixture("partitions.txt"))

    assert [partition.name for partition in partitions] == ["compute", "gpu", "long"]
    assert partitions[0].availability is True
    assert partitions[0].state == "UP"
    assert partitions[0].time_limit == "2-00:00:00"
    assert (
        partitions[0].allocated_node_count,
        partitions[0].idle_node_count,
        partitions[0].other_node_count,
        partitions[0].node_count,
    ) == (2, 1, 1, 4)
    assert partitions[1].availability is False
    assert partitions[1].time_limit == "UNLIMITED"
    assert partitions[2].time_limit is None


def test_parses_node_fixture_and_normalizes_resources() -> None:
    nodes = parse_nodes_text(_fixture("nodes.txt"))

    assert [node.name for node in nodes] == ["cpu001", "cpu002", "cpu003", "cpu004"]
    assert nodes[0].partition_names == ["compute"]
    assert nodes[0].state is NodeState.IDLE
    assert nodes[0].allocated_memory_mb == 12_144

    gpu_node = nodes[1]
    assert gpu_node.partition_names == ["compute", "gpu"]
    assert gpu_node.state is NodeState.MIXED
    assert gpu_node.cpu_count == 64
    assert gpu_node.allocated_cpus == 32
    assert gpu_node.memory_mb == 262_144
    assert gpu_node.allocated_memory_mb == 131_072
    assert gpu_node.generic_resources == ["gpu:a100:4(S:0-3)", "mps:100"]
    assert gpu_node.gpu_resources == ["gpu:a100:4(S:0-3)"]

    drained_node = nodes[2]
    assert drained_node.state is NodeState.DRAINED
    assert drained_node.allocated_memory_mb is None
    assert drained_node.reason == "Hardware failure | ticket #42"
    assert drained_node.gpu_resources == ["gpu:h100:2(IDX:0-1)"]

    assert nodes[3].state is NodeState.DOWN


def test_parses_squeue_fixture() -> None:
    jobs = parse_squeue_jobs_text(_fixture("squeue_jobs.txt"))

    assert [job.job_id for job in jobs] == ["301", "302", "303"]
    running = jobs[0]
    assert running.array_job_id is None
    assert running.heterogeneous_job_id is None
    assert running.state is JobState.RUNNING
    assert running.reason is None
    assert running.node_list == ["cpu002"]
    assert running.requested_memory_mb == 196_608
    assert running.requested_gpus == 2
    assert running.elapsed_seconds == 3_723
    assert running.time_limit_seconds == 86_400
    assert running.submit_time == datetime(
        2026,
        7,
        26,
        8,
        55,
        tzinfo=timezone(timedelta(hours=2)),
    )

    pending = jobs[1]
    assert pending.state is JobState.PENDING
    assert pending.reason == "Resources"
    assert pending.node_list == []
    assert pending.requested_memory_mb == 131_072
    assert pending.requested_gpus == 4
    assert pending.start_time is None
    assert pending.elapsed_seconds == 0
    assert pending.time_limit_seconds == 21_600

    configuring = jobs[2]
    assert configuring.state is JobState.PENDING
    assert configuring.node_list == ["node[01-02,04]"]
    assert configuring.requested_gpus is None
    assert configuring.elapsed_seconds == 93_784
    assert configuring.time_limit_seconds is None
    assert configuring.reason == "Configuration | waiting"


def test_parses_sacct_fixture_and_ignores_job_steps() -> None:
    jobs = parse_sacct_jobs_text(_fixture("sacct_jobs.txt"))

    assert [job.job_id for job in jobs] == ["290", "291", "292"]
    completed = jobs[0]
    assert completed.state is JobState.COMPLETED
    assert completed.requested_memory_mb == 2_048
    assert completed.requested_gpus == 2
    assert completed.elapsed_seconds == 2_701
    assert completed.end_time == datetime(
        2026,
        7,
        25,
        8,
        50,
        1,
        tzinfo=timezone(timedelta(hours=2)),
    )

    failed = jobs[1]
    assert failed.state is JobState.OUT_OF_MEMORY
    assert failed.node_list == ["cpu[001-002]"]
    assert failed.requested_memory_mb == 4_096
    assert failed.requested_gpus == 0
    assert failed.elapsed_seconds == 90_000
    assert failed.time_limit_seconds == 172_800

    cancelled = jobs[2]
    assert cancelled.state is JobState.CANCELLED
    assert cancelled.node_list == []
    assert cancelled.start_time is None
    assert cancelled.end_time is None
    assert cancelled.time_limit_seconds is None
    assert cancelled.reason == "Priority | QOS cap"


def test_preserves_array_and_heterogeneous_scope_from_fixed_formats() -> None:
    queue_jobs = parse_squeue_jobs_text(_fixture("squeue_scoped_jobs.txt"))
    accounting_jobs = parse_sacct_jobs_text(_fixture("sacct_scoped_jobs.txt"))

    queue_array, queue_heterogeneous = queue_jobs
    assert queue_array.job_id == "42000_[1-128%8]"
    assert queue_array.array_job_id == "42000"
    assert queue_array.array_task_id == "1-128%8"
    assert queue_array.heterogeneous_job_id is None
    assert queue_heterogeneous.job_id == "43000+0"
    assert queue_heterogeneous.heterogeneous_job_id == "43000"
    assert queue_heterogeneous.heterogeneous_job_offset == 0

    accounting_array, accounting_heterogeneous = accounting_jobs
    assert accounting_array.job_id == "42000"
    assert accounting_array.array_job_id == "42000"
    assert accounting_array.array_task_id == "7"
    assert accounting_heterogeneous.job_id == "43000"
    assert accounting_heterogeneous.heterogeneous_job_id == "43000"
    assert accounting_heterogeneous.heterogeneous_job_offset == 0


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("59", 59),
        ("3600", 3_600),
        ("02:03", 123),
        ("01:02:03", 3_723),
        ("1-02:03:04", 93_784),
        ("00:00:01.999", 1),
        ("UNLIMITED", None),
        ("Partition_Limit", None),
        ("N/A", None),
        ("bad", None),
        ("00:00:01.nope", None),
        ("00:61:00", None),
    ],
)
def test_parses_slurm_durations(raw: str, expected: int | None) -> None:
    assert parse_slurm_duration(raw) == expected


@pytest.mark.parametrize(
    ("raw", "cpus", "nodes", "expected"),
    [
        ("1024K", None, None, 1),
        ("1024M", None, None, 1_024),
        ("1.5G", None, None, 1_536),
        ("2Gc", 8, 1, 16_384),
        ("64Gn", 16, 2, 131_072),
        ("1TiB", None, None, 1_048_576),
        ("1048576B", None, None, 1),
        ("N/A", None, None, None),
        ("12XB", None, None, None),
    ],
)
def test_parses_slurm_memory(
    raw: str,
    cpus: int | None,
    nodes: int | None,
    expected: int | None,
) -> None:
    assert parse_slurm_memory_mb(raw, cpus=cpus, nodes=nodes) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("gpu:a100:4", 4),
        ("gpu:a100:2(S:0-1),gpu:h100:1", 3),
        ("gres/gpu=2,gres/gpu:a100=2", 2),
        ("gres/gpu:a100=2,gres/gpu:h100=4", 6),
        ("cpu=32,mem=128G,node=2", 0),
        ("N/A", None),
    ],
)
def test_parses_gpu_counts(raw: str, expected: int | None) -> None:
    assert parse_slurm_gpu_count(raw) == expected


def test_preserves_bracketed_node_ranges_and_resource_topology() -> None:
    assert parse_slurm_node_list("cpu[001-003,008],gpu009") == [
        "cpu[001-003,008]",
        "gpu009",
    ]
    assert parse_slurm_resource_list("gpu:a100:2(S:0,1),mps:100") == [
        "gpu:a100:2(S:0,1)",
        "mps:100",
    ]


def test_parses_iso_and_epoch_timestamps() -> None:
    assert parse_slurm_timestamp("2026-07-26T12:00:00Z") == datetime(
        2026,
        7,
        26,
        12,
        tzinfo=UTC,
    )
    assert parse_slurm_timestamp("0") is None
    assert parse_slurm_timestamp("not a timestamp") is None
    assert parse_slurm_timestamp("1767225600") == datetime(2026, 1, 1, tzinfo=UTC)


def test_rejects_non_fixed_field_output_without_echoing_contents() -> None:
    with pytest.raises(SlurmTextParseError) as caught:
        parse_squeue_jobs_text("JOBID PARTITION NAME USER ST TIME NODES NODELIST")

    assert caught.value.record_kind == "squeue job"
    assert caught.value.line_number == 1
    assert caught.value.expected_fields == 19
    assert "JOBID" not in str(caught.value)


def test_ignores_empty_lines_and_accepts_optional_trailing_delimiter() -> None:
    output = "\ncompute|up|1-00:00:00|1|0/1/0/1|\n\n"

    partitions = parse_partitions_text(output)

    assert len(partitions) == 1
    assert partitions[0].name == "compute"
