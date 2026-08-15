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
_LOG_JOB_ID = re.compile(r"^[1-9][0-9]*(?:_[0-9]+)?$")
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
_REMOTE_FILE_HELPER = r"""import base64
import json
import os
import stat
import sys

MAX_BYTES = 1048576
MAX_ENTRIES = 500

def emit(value):
    print(json.dumps(value, ensure_ascii=True, separators=(",", ":")))

def kind(mode):
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"

def metadata(path, name):
    info = os.lstat(path)
    entry_kind = kind(info.st_mode)
    target_kind = None
    target = None
    if entry_kind == "symlink":
        try:
            target = os.readlink(path)
            target_kind = kind(os.stat(path).st_mode)
        except OSError:
            pass
    return {
        "name": name,
        "path": path,
        "kind": entry_kind,
        "target_kind": target_kind,
        "size_bytes": max(0, info.st_size),
        "modified_at": info.st_mtime,
        "permissions": stat.filemode(info.st_mode),
        "readable": os.access(path, os.R_OK),
        "symlink_target": target,
    }

action = sys.argv[1]
requested = sys.argv[2]
show_hidden = sys.argv[3] == "1"
try:
    if requested:
        if not os.path.isabs(requested) or "\0" in requested or len(requested.encode()) > 4096:
            emit({"error": "invalid_path"})
            raise SystemExit(0)
        selected = os.path.abspath(requested)
    else:
        selected = os.getcwd()

    if action == "list":
        canonical = os.path.realpath(selected)
        if not stat.S_ISDIR(os.stat(canonical).st_mode):
            emit({"error": "not_directory"})
            raise SystemExit(0)
        entries = []
        with os.scandir(canonical) as directory:
            for entry in directory:
                if not show_hidden and entry.name.startswith("."):
                    continue
                try:
                    entries.append(metadata(os.path.join(canonical, entry.name), entry.name))
                except FileNotFoundError:
                    continue
        entries.sort(key=lambda item: (
            item["kind"] != "directory" and item.get("target_kind") != "directory",
            item["name"].casefold(),
            item["name"],
        ))
        truncated = len(entries) > MAX_ENTRIES
        emit({
            "path": canonical,
            "parent_path": None if canonical == "/" else os.path.dirname(canonical),
            "entries": entries[:MAX_ENTRIES],
            "truncated": truncated,
        })
    elif action == "preview":
        original = metadata(selected, os.path.basename(selected) or "/")
        canonical = os.path.realpath(selected)
        target_info = os.stat(canonical)
        response = {
            "path": selected,
            "name": original["name"],
            "kind": original["kind"],
            "size_bytes": max(0, target_info.st_size),
            "modified_at": target_info.st_mtime,
            "permissions": stat.filemode(target_info.st_mode),
            "symlink_target": original.get("symlink_target"),
        }
        if not stat.S_ISREG(target_info.st_mode):
            response["status"] = "special"
        elif target_info.st_size > MAX_BYTES:
            response["status"] = "too_large"
        elif not os.access(canonical, os.R_OK):
            emit({"error": "forbidden"})
            raise SystemExit(0)
        else:
            with open(canonical, "rb") as source:
                content = source.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                response["status"] = "too_large"
            elif b"\0" in content:
                response["status"] = "binary"
            else:
                try:
                    content.decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    response["status"] = "binary"
                else:
                    response["status"] = "available"
                    response["content_base64"] = base64.b64encode(content).decode("ascii")
        emit(response)
    else:
        emit({"error": "invalid_path"})
except FileNotFoundError:
    emit({"error": "not_found"})
except PermissionError:
    emit({"error": "forbidden"})
except (OSError, ValueError):
    emit({"error": "invalid_path"})
"""


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


def build_scontrol_partitions_json_command() -> SlurmCommand:
    return SlurmCommand(
        "scontrol",
        ("--json", "show", "partition"),
        "scontrol_partitions_json",
    )


def build_scontrol_nodes_json_command() -> SlurmCommand:
    return SlurmCommand(
        "scontrol",
        ("--json", "show", "node"),
        "scontrol_nodes_json",
    )


def build_topology_command() -> SlurmCommand:
    return SlurmCommand("scontrol", ("show", "topology"), "scontrol_topology")


def build_remote_files_command(
    action: str,
    path: str | None,
    *,
    show_hidden: bool = False,
) -> SlurmCommand:
    if action not in {"list", "preview"}:
        raise ValueError("unsupported remote file operation")
    selected_path = path or ""
    if "\x00" in selected_path or len(selected_path.encode("utf-8")) > 4096:
        raise ValueError("remote path is invalid")
    if selected_path and not selected_path.startswith("/"):
        raise ValueError("remote path must be absolute")
    return SlurmCommand(
        "python3",
        ("-I", "-c", _REMOTE_FILE_HELPER, action, selected_path, "1" if show_hidden else "0"),
        f"remote_files_{action}",
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
    expand_patterns: bool = False,
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
    if expand_patterns:
        arguments.append("--expand-patterns")
        command_type = "sacct_job_logs_json"
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


def build_sacct_job_logs_text_command(user: str, job_id: str) -> SlurmCommand:
    return SlurmCommand(
        "sacct",
        (
            "--allocations",
            "--parsable2",
            "--noheader",
            f"--user={_validated_user(user)}",
            f"--jobs={_validated_log_job_id(job_id)}",
            "--expand-patterns",
            "--format=JobIDRaw,JobID,User,State,WorkDir,StdOut,StdErr,JobName,"
            "ArrayJobID,ArrayTaskID,HetJobID,HetJobOffset",
        ),
        "sacct_job_logs_text",
    )


def build_scontrol_job_json_command(job_id: str) -> SlurmCommand:
    return SlurmCommand(
        "scontrol",
        ("--json", "show", "job", _validated_log_job_id(job_id)),
        "scontrol_job_logs_json",
    )


def build_scontrol_job_text_command(job_id: str) -> SlurmCommand:
    return SlurmCommand(
        "scontrol",
        ("show", "job", "--oneliner", _validated_log_job_id(job_id)),
        "scontrol_job_logs_text",
    )


def build_file_test_command(path: str, predicate: str) -> SlurmCommand:
    if predicate not in {"exists", "regular", "readable"}:
        raise ValueError("unsupported file-test predicate")
    if not path or "\x00" in path:
        raise ValueError("path must be non-empty and contain no NUL bytes")
    option = {"exists": "-e", "regular": "-f", "readable": "-r"}[predicate]
    return SlurmCommand("test", (option, path), f"job_log_file_{predicate}")


def build_tail_command(path: str, *, initial_lines: int, follow: bool) -> SlurmCommand:
    if not path or "\x00" in path:
        raise ValueError("path must be non-empty and contain no NUL bytes")
    if initial_lines < 0 or initial_lines > 10_000:
        raise ValueError("initial_lines must be between zero and 10000")
    arguments = [f"--lines={initial_lines}"]
    if follow:
        arguments.extend(("--follow=name", "--retry"))
    arguments.extend(("--", path))
    return SlurmCommand("tail", tuple(arguments), "job_log_tail")


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


def _validated_log_job_id(job_id: str) -> str:
    if not _LOG_JOB_ID.fullmatch(job_id):
        raise ValueError("job_id must be an allocation or explicit numeric array-task ID")
    return job_id


def _validated_cancel_job_id(job_id: str) -> str:
    if not job_id.isascii() or not job_id.isdigit() or job_id.startswith("0"):
        raise ValueError("cancellation requires one positive numeric Slurm job ID")
    return job_id
