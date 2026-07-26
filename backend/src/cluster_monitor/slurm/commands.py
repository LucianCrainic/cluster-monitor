"""Safe Slurm command specifications.

Every command is represented as an executable plus an argument tuple. Dynamic
filters are validated here and are always carried inside an option value; the
SSH executor still performs the final remote-shell quoting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cluster_monitor.models import JobSubmissionRequest
from cluster_monitor.slurm.text_parser import (
    NODE_SINFO_FORMAT,
    PARTITION_SINFO_FORMAT,
    SACCT_JOB_FIELDS,
    SQUEUE_JOB_FORMAT,
)

_SLURM_USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9_.+\-]{1,128}$")
_SAFE_WRAPPER_EXECUTABLE = "/usr/bin/env"
_SBATCH_WRAPPER_SOURCE = (
    'for name in "${!SBATCH_@}"; do unset "$name"; done; unset SLURM_CLUSTERS; exec sbatch "$@"'
)
_SBATCH_WRAPPER_PREFIX = (
    "-u",
    "BASH_ENV",
    "-u",
    "ENV",
    "/bin/bash",
    "--noprofile",
    "--norc",
    "-p",
    "-c",
    _SBATCH_WRAPPER_SOURCE,
    "cluster-monitor-sbatch",
)


@dataclass(frozen=True, slots=True)
class SlurmCommand:
    executable: str
    arguments: tuple[str, ...]
    command_type: str


def build_version_command() -> SlurmCommand:
    return SlurmCommand("sinfo", ("--version",), "slurm_version")


def build_sinfo_json_probe() -> SlurmCommand:
    return SlurmCommand(
        "sinfo",
        ("--json", "--states=FUTURE"),
        "sinfo_json_probe",
    )


def build_squeue_json_probe() -> SlurmCommand:
    return SlurmCommand(
        "squeue",
        ("--json", "--states=COMPLETED"),
        "squeue_json_probe",
    )


def build_sacct_json_probe() -> SlurmCommand:
    return SlurmCommand(
        "sacct",
        ("--json", "--allocations", "--starttime=now", "--endtime=now"),
        "sacct_json_probe",
    )


def build_remote_user_command() -> SlurmCommand:
    return SlurmCommand("id", ("-un",), "remote_user")


def build_partitions_json_command() -> SlurmCommand:
    return SlurmCommand("sinfo", ("--json",), "sinfo_partitions_json")


def build_partitions_text_command() -> SlurmCommand:
    return SlurmCommand(
        "sinfo",
        ("--noheader", "--summarize", f"--format={PARTITION_SINFO_FORMAT}"),
        "sinfo_partitions_text",
    )


def build_nodes_json_command() -> SlurmCommand:
    return SlurmCommand("sinfo", ("--json", "--Node"), "sinfo_nodes_json")


def build_nodes_text_command() -> SlurmCommand:
    return SlurmCommand(
        "sinfo",
        ("--noheader", "--Node", "--exact", f"--format={NODE_SINFO_FORMAT}"),
        "sinfo_nodes_text",
    )


def build_squeue_json_command(user: str) -> SlurmCommand:
    selected_user = _validated_user(user)
    return SlurmCommand(
        "squeue",
        ("--json", f"--user={selected_user}"),
        "squeue_jobs_json",
    )


def build_squeue_text_command(user: str) -> SlurmCommand:
    selected_user = _validated_user(user)
    return SlurmCommand(
        "squeue",
        ("--noheader", f"--user={selected_user}", f"--Format={SQUEUE_JOB_FORMAT}"),
        "squeue_jobs_text",
    )


def build_sacct_json_command(
    user: str,
    *,
    job_id: str | None = None,
) -> SlurmCommand:
    arguments = [
        "--json",
        "--allocations",
        f"--user={_validated_user(user)}",
        "--starttime=now-7days",
    ]
    command_type = "sacct_jobs_json"
    if job_id is not None:
        arguments.append(f"--jobs={_validated_job_id(job_id)}")
        command_type = "sacct_job_json"
    return SlurmCommand("sacct", tuple(arguments), command_type)


def build_sacct_text_command(
    user: str,
    *,
    job_id: str | None = None,
) -> SlurmCommand:
    arguments = [
        "--allocations",
        "--parsable2",
        "--noheader",
        f"--user={_validated_user(user)}",
        "--starttime=now-7days",
        f"--format={','.join(SACCT_JOB_FIELDS)}",
    ]
    command_type = "sacct_jobs_text"
    if job_id is not None:
        arguments.append(f"--jobs={_validated_job_id(job_id)}")
        command_type = "sacct_job_text"
    return SlurmCommand("sacct", tuple(arguments), command_type)


def build_sbatch_command(request: JobSubmissionRequest) -> SlurmCommand:
    """Build a bounded sbatch invocation that reads the script from stdin.

    A static privileged-mode Bash wrapper removes every exported ``SBATCH_*``
    variable and ``SLURM_CLUSTERS`` immediately before ``exec``. Ordinary
    login and module environment variables remain available for Slurm to
    export into the job. ``BASH_ENV`` and ``ENV`` are removed before Bash
    starts, and request data is passed only through positional arguments.
    """

    arguments = [
        *_SBATCH_WRAPPER_PREFIX,
        "--parsable",
        f"--job-name={request.job_name}",
        f"--nodes={request.nodes}",
        f"--cpus-per-task={request.cpus_per_task}",
        f"--time={request.time_limit_minutes}",
    ]
    if request.partition is not None:
        arguments.append(f"--partition={request.partition}")
    if request.memory_mb is not None:
        arguments.append(f"--mem={request.memory_mb}M")
    if request.gpus_per_node:
        arguments.append(f"--gres=gpu:{request.gpus_per_node}")
    return SlurmCommand(_SAFE_WRAPPER_EXECUTABLE, tuple(arguments), "sbatch_submit")


def build_scancel_command(job_id: str) -> SlurmCommand:
    return SlurmCommand(
        "scancel",
        ("--quiet", _validated_cancel_job_id(job_id)),
        "scancel_job",
    )


def _validated_user(user: str) -> str:
    if not _SLURM_USER.fullmatch(user):
        raise ValueError("user must be a valid Slurm account name")
    return user


def _validated_job_id(job_id: str) -> str:
    if not _JOB_ID.fullmatch(job_id):
        raise ValueError("job_id must be a valid Slurm job identifier")
    return job_id


def _validated_cancel_job_id(job_id: str) -> str:
    if not job_id.isascii() or not job_id.isdigit() or job_id.startswith("0"):
        raise ValueError("cancellation requires one positive numeric Slurm job ID")
    return job_id
