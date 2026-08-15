from __future__ import annotations

import json
from dataclasses import replace

import pytest

from cluster_monitor.models import JobState
from cluster_monitor.slurm.job_logs import (
    JobLogMetadata,
    JobLogMetadataParseError,
    parse_sacct_job_logs_text,
    parse_scontrol_job_logs_json,
    parse_scontrol_job_logs_text,
    resolve_log_paths,
    validate_log_job_id,
)


def test_parses_scontrol_json_and_resolves_relative_merged_array_path() -> None:
    output = json.dumps(
        {
            "jobs": [
                {
                    "job_id": "12345_7",
                    "name": "array sample",
                    "user_name": "researcher",
                    "job_state": ["RUNNING"],
                    "current_working_directory": "/home/researcher/work",
                    "standard_output": "logs/%A_%a_%x.out",
                    "standard_error": "logs/%A_%a_%x.out",
                    "array_job_id": 12345,
                    "array_task_id": 7,
                }
            ]
        }
    )

    metadata = parse_scontrol_job_logs_json(output, "12345_7")

    assert metadata is not None
    assert metadata.state is JobState.RUNNING
    assert resolve_log_paths(metadata) == {
        "combined": "/home/researcher/work/logs/12345_7_array sample.out"
    }


def test_real_scontrol_optional_id_wrappers_do_not_mark_plain_job_as_scoped() -> None:
    output = json.dumps(
        {
            "jobs": [
                {
                    "job_id": 982274,
                    "name": "cluster-monitor-job",
                    "user_name": "researcher",
                    "job_state": ["COMPLETED"],
                    "current_working_directory": "/home/researcher",
                    "standard_output": "/home/researcher/slurm-982274.out",
                    "standard_error": "/home/researcher/slurm-982274.out",
                    "array_job_id": {
                        "set": True,
                        "infinite": False,
                        "number": 0,
                    },
                    "array_task_id": {
                        "set": False,
                        "infinite": False,
                        "number": 0,
                    },
                    "het_job_id": {
                        "set": True,
                        "infinite": False,
                        "number": 0,
                    },
                    "het_job_offset": {
                        "set": True,
                        "infinite": False,
                        "number": 0,
                    },
                }
            ]
        }
    )

    metadata = parse_scontrol_job_logs_json(output, "982274")

    assert metadata is not None
    assert metadata.array_job_id is None
    assert metadata.array_task_id is None
    assert metadata.heterogeneous_job_id is None
    assert metadata.heterogeneous_job_offset is None
    assert metadata.ambiguous_array_leader is False
    assert resolve_log_paths(metadata) == {"combined": "/home/researcher/slurm-982274.out"}


def test_parses_scontrol_oneliner_without_splitting_spaces_in_values() -> None:
    output = (
        "JobId=321 JobName=my experiment UserId=researcher(1000) JobState=PENDING "
        "WorkDir=/home/researcher/my work StdOut=logs/321.out StdErr=logs/321.err\n"
    )

    metadata = parse_scontrol_job_logs_text(output, "321")

    assert metadata is not None
    assert metadata.job_name == "my experiment"
    assert metadata.user == "researcher"
    assert metadata.working_directory == "/home/researcher/my work"


def test_parses_exact_sacct_allocation_and_ignores_steps() -> None:
    output = (
        "44.batch|44.batch|researcher|COMPLETED|/work|step.out|step.err|batch||\n"
        "44|44|researcher|COMPLETED|/work|final.out|final.err|job||\n"
    )

    metadata = parse_sacct_job_logs_text(output, "44")

    assert metadata is not None
    assert metadata.stdout_path == "final.out"
    assert metadata.terminal is True


def test_preserves_heterogeneous_scope_from_sacct() -> None:
    output = "43000|43000+0|researcher|RUNNING|/work|job.out|job.err|coupled|||43000|0\n"

    metadata = parse_sacct_job_logs_text(output, "43000")

    assert metadata is not None
    assert metadata.heterogeneous_job_id == "43000"
    assert metadata.heterogeneous_job_offset == "0"


def test_sacct_zero_scope_ids_are_absent_for_plain_jobs() -> None:
    output = "44|44|researcher|COMPLETED|/work|job.out||job|0|0|0|0\n"

    metadata = parse_sacct_job_logs_text(output, "44")

    assert metadata is not None
    assert metadata.array_job_id is None
    assert metadata.array_task_id is None
    assert metadata.heterogeneous_job_id is None
    assert metadata.heterogeneous_job_offset is None


def test_rejects_unsafe_ids_and_unresolved_or_invalid_paths() -> None:
    for job_id in ("123.batch", "123+1", "123;touch", "0"):
        with pytest.raises(ValueError):
            validate_log_job_id(job_id)

    base = JobLogMetadata(
        job_id="123",
        user="researcher",
        state=JobState.RUNNING,
        state_raw="RUNNING",
        job_name="job",
        working_directory="/work",
        stdout_path="slurm-%N.out",
        stderr_path=None,
    )
    with pytest.raises(JobLogMetadataParseError, match="unsupported"):
        resolve_log_paths(base)

    with pytest.raises(JobLogMetadataParseError, match="work directory"):
        resolve_log_paths(replace(base, working_directory=None, stdout_path="relative.out"))


def test_dev_null_and_missing_paths_are_unavailable() -> None:
    metadata = JobLogMetadata(
        job_id="123",
        user="researcher",
        state=JobState.COMPLETED,
        state_raw="COMPLETED",
        job_name="job",
        working_directory="/work",
        stdout_path="/dev/null",
        stderr_path="None",
    )

    assert resolve_log_paths(metadata) == {}


def test_expanded_sacct_path_can_contain_a_literal_percent() -> None:
    metadata = JobLogMetadata(
        job_id="123",
        user="researcher",
        state=JobState.COMPLETED,
        state_raw="COMPLETED",
        job_name="job",
        working_directory="/work",
        stdout_path="/work/progress%done.out",
        stderr_path=None,
        patterns_expanded=True,
    )

    assert resolve_log_paths(metadata) == {"stdout": "/work/progress%done.out"}
