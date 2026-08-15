"""Tolerant parsers for Slurm's versioned JSON data-parser output.

Slurm JSON schemas change with the installed ``data_parser`` plugin.  The
helpers in this module target the 24.11 shape while accepting the scalar and
nested aliases seen in adjacent releases.  Parser failures deliberately never
include command output because scheduler responses can contain usernames,
paths, commands, and other sensitive cluster data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from cluster_monitor.models import AccountingInfo, Job, JobDetails, Node, Partition
from cluster_monitor.slurm.normalization import normalize_job_state, normalize_node_state
from cluster_monitor.slurm.text_parser import (
    parse_slurm_duration,
    parse_slurm_gpu_count,
    parse_slurm_memory_mb,
    parse_slurm_node_list,
    parse_slurm_resource_list,
    parse_slurm_timestamp,
)

JsonObject = Mapping[str, object]
JsonPath = tuple[str, ...]

_INFINITE = object()
_MISSING_TEXT = frozenset(
    {
        "",
        "-",
        "n/a",
        "na",
        "none",
        "(null)",
        "null",
        "unknown",
        "not_set",
        "none assigned",
    }
)
_TERMINAL_STEP_SUFFIXES = (".batch", ".extern", ".interactive")
_ARRAY_JOB_IDENTIFIER = re.compile(r"^(?P<job_id>[1-9][0-9]*)_(?P<task_id>.+)$")
_HETEROGENEOUS_JOB_IDENTIFIER = re.compile(r"^(?P<job_id>[1-9][0-9]*)\+(?P<offset>[0-9]+)$")
_SLURM_NO_VALUE_IDS = frozenset({"4294967294", "4294967295"})


class SlurmJsonParseError(ValueError):
    """A Slurm JSON response could not be safely normalized."""

    def __init__(self, response_kind: str, reason: str) -> None:
        super().__init__(f"Could not parse the {response_kind} Slurm JSON response: {reason}.")
        self.response_kind = response_kind
        self.reason = reason


def parse_partitions_json(output: str) -> list[Partition]:
    """Parse partition summaries from ``sinfo --json`` output."""

    payload = _load_payload(output, "partition")
    records = _sinfo_partition_records(payload)
    try:
        parsed = [_parse_partition(record, index) for index, record in enumerate(records)]
        return _merge_partition_rows(parsed)
    except (TypeError, ValueError, OverflowError):
        raise SlurmJsonParseError("partition", "a partition record is invalid") from None


def parse_nodes_json(output: str) -> list[Node]:
    """Parse node records from ``sinfo --json`` output."""

    payload = _load_payload(output, "node")
    records = _sinfo_node_records(payload)
    try:
        return [_parse_node(record, index) for index, record in enumerate(records)]
    except (TypeError, ValueError, OverflowError):
        raise SlurmJsonParseError("node", "a node record is invalid") from None


def parse_squeue_jobs_json(output: str) -> list[Job]:
    """Parse active jobs from ``squeue --json`` output."""

    payload = _load_payload(output, "queue")
    records = _job_records(payload)
    try:
        return [_parse_job(record, "squeue", index) for index, record in enumerate(records)]
    except (TypeError, ValueError, OverflowError):
        raise SlurmJsonParseError("queue", "a job record is invalid") from None


def parse_sacct_jobs_json(output: str) -> list[Job]:
    """Parse allocation rows from ``sacct --json`` and sort newest first."""

    payload = _load_payload(output, "accounting")
    records = _job_records(payload)
    jobs: list[Job] = []
    try:
        for index, record in enumerate(records):
            job_id = _job_id(record)
            if _is_step_id(job_id):
                continue
            jobs.append(_parse_job(record, "sacct", index))
    except (TypeError, ValueError, OverflowError):
        raise SlurmJsonParseError("accounting", "a job record is invalid") from None

    jobs.sort(key=_job_sort_key, reverse=True)
    return jobs


def parse_sacct_job_details_json(output: str, job_id: str) -> JobDetails | None:
    """Parse one allocation and its accounting steps from ``sacct --json``.

    ``None`` means that the requested allocation is not present.  Step rows are
    never returned as jobs, but their utilization values can enrich the parent
    allocation.
    """

    payload = _load_payload(output, "job details")
    records = _job_records(payload)
    allocation: JsonObject | None = None
    related_steps: list[JsonObject] = []

    try:
        for record in records:
            record_id = _job_id(record)
            if record_id == job_id and not _is_step_id(record_id):
                allocation = record
            elif _belongs_to_job_step(record_id, job_id):
                related_steps.append(record)

        if allocation is None:
            return None

        job = _parse_job(allocation, "sacct", 0)
        accounting = _parse_accounting(allocation, related_steps)
        return JobDetails(
            **job.model_dump(),
            working_directory=_optional_text(
                _first(
                    allocation,
                    ("working_directory",),
                    ("work_dir",),
                    ("workdir",),
                    ("paths", "working_directory"),
                    ("paths", "work_dir"),
                )
            ),
            command=_optional_text(
                _first(
                    allocation,
                    ("command",),
                    ("script",),
                    ("submit_line",),
                    ("paths", "command"),
                )
            ),
            standard_output_path=_optional_text(
                _first(
                    allocation,
                    ("standard_output",),
                    ("stdout_expanded",),
                    ("stdout",),
                    ("std_out",),
                    ("paths", "standard_output"),
                    ("paths", "stdout"),
                    ("paths", "output"),
                )
            ),
            standard_error_path=_optional_text(
                _first(
                    allocation,
                    ("standard_error",),
                    ("stderr_expanded",),
                    ("stderr",),
                    ("std_err",),
                    ("paths", "standard_error"),
                    ("paths", "stderr"),
                    ("paths", "error"),
                )
            ),
            exit_code=_exit_code(
                _first(
                    allocation,
                    ("exit_code",),
                    ("derived_exit_code",),
                    ("state", "exit_code"),
                )
            ),
            allocation_details={
                "nodes": job.nodes,
                "cpus": job.requested_cpus,
                "memory_mb": job.requested_memory_mb,
                "gpus": job.requested_gpus,
            },
            accounting=accounting,
        )
    except (TypeError, ValueError, OverflowError):
        raise SlurmJsonParseError("job details", "the requested job record is invalid") from None


def _load_payload(output: str, response_kind: str) -> JsonObject:
    try:
        decoded: object = json.loads(output)
    except json.JSONDecodeError:
        raise SlurmJsonParseError(response_kind, "the response is not valid JSON") from None

    payload = _as_object(decoded)
    if payload is None:
        raise SlurmJsonParseError(response_kind, "the top-level value is not an object")
    if _has_errors(payload):
        raise SlurmJsonParseError(response_kind, "Slurm reported an error")
    return payload


def _has_errors(payload: JsonObject) -> bool:
    candidates = [
        payload.get("errors"),
        _at(payload, ("meta", "errors")),
        _at(payload, ("sinfo", "errors")),
        _at(payload, ("jobs", "errors")),
        _at(payload, ("nodes", "errors")),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        sequence = _as_sequence(candidate)
        if sequence is not None:
            if sequence:
                return True
            continue
        mapping = _as_object(candidate)
        if mapping is not None:
            if mapping:
                return True
            continue
        if bool(candidate):
            return True
    return False


def _sinfo_partition_records(payload: JsonObject) -> list[JsonObject]:
    candidates = (
        payload.get("sinfo"),
        payload.get("partitions"),
        _at(payload, ("sinfo", "partitions")),
        _at(payload, ("sinfo", "sinfo")),
    )
    for candidate in candidates:
        records = _record_list(candidate)
        if records is not None:
            return records
    return []


def _sinfo_node_records(payload: JsonObject) -> list[JsonObject]:
    candidates = (
        _at(payload, ("nodes", "nodes")),
        payload.get("nodes"),
        _at(payload, ("sinfo", "nodes", "nodes")),
        _at(payload, ("sinfo", "nodes")),
        # Slurm 23.11+ ``sinfo --Node`` returns node rows here.
        payload.get("sinfo"),
    )
    for candidate in candidates:
        records = _record_list(candidate)
        if records is not None:
            return records
    return []


def _job_records(payload: JsonObject) -> list[JsonObject]:
    candidates = (
        payload.get("jobs"),
        _at(payload, ("jobs", "jobs")),
        _at(payload, ("squeue", "jobs")),
        _at(payload, ("sacct", "jobs")),
    )
    for candidate in candidates:
        records = _record_list(candidate)
        if records is not None:
            return records
    return []


def _record_list(value: object | None) -> list[JsonObject] | None:
    sequence = _as_sequence(value)
    if sequence is not None:
        records: list[JsonObject] = []
        for item in sequence:
            record = _as_object(item)
            if record is None:
                raise ValueError("record is not an object")
            records.append(record)
        return records

    mapping = _as_object(value)
    if mapping is None:
        return None
    for key in ("records", "items", "partitions", "nodes", "jobs", "sinfo"):
        nested = _as_sequence(mapping.get(key))
        if nested is not None:
            return _record_list(nested)
    return None


def _parse_partition(record: JsonObject, index: int) -> Partition:
    del index
    reported_name = _required_text(
        _first(record, ("partition", "name"), ("name",), ("partition_name",)),
        "partition name",
    )
    name = reported_name.removesuffix("*")
    state_raw = _state_text(
        _first(
            record,
            ("partition", "partition", "state"),
            ("partition", "state"),
            ("state",),
            ("availability",),
        )
    )
    if not state_raw:
        state_raw = "UNKNOWN"

    maximum_time = _first(
        record,
        ("maximums", "time"),
        ("maximum_time",),
        ("time_limit",),
        ("partition", "maximums", "time"),
    )
    time_limit = _partition_time_limit(maximum_time)

    allocated = _nonnegative_int(
        _first(
            record,
            ("nodes", "allocation", "allocated"),
            ("nodes", "allocated"),
            ("allocated_nodes",),
            ("allocated_node_count",),
        )
    )
    idle = _nonnegative_int(
        _first(
            record,
            ("nodes", "allocation", "idle"),
            ("nodes", "idle"),
            ("idle_nodes",),
            ("idle_node_count",),
        )
    )
    other = _nonnegative_int(
        _first(
            record,
            ("nodes", "allocation", "other"),
            ("nodes", "other"),
            ("other_nodes",),
            ("other_node_count",),
        )
    )
    total = _nonnegative_int(
        _first(
            record,
            ("nodes", "allocation", "total"),
            ("nodes", "total"),
            ("total_nodes",),
            ("node_count",),
        )
    )
    allocated = allocated or 0
    idle = idle or 0
    other = other or 0
    total = total if total is not None else allocated + idle + other

    state_components = {part.casefold() for part in state_raw.replace("+", " ").split()}
    availability = bool(state_components & {"up", "active", "available"})
    default_value = _unwrap(_first(record, ("default",), ("partition", "default")))
    flags = {flag.casefold() for flag in _name_list(_first(record, ("flags",)))}
    return Partition(
        name=name,
        availability=availability,
        state=state_raw,
        time_limit=time_limit,
        node_count=total,
        allocated_node_count=allocated,
        idle_node_count=idle,
        other_node_count=other,
        is_default=(
            reported_name.endswith("*")
            or default_value is True
            or (
                isinstance(default_value, str)
                and default_value.casefold() in {"true", "yes", "default"}
            )
            or "default" in flags
        ),
        node_names=_node_list(_first(record, ("nodes", "configured"), ("node_names",))),
        qos=_name_list(
            _first(
                record,
                ("qos", "assigned"),
                ("qos", "allowed"),
                ("qos",),
                ("quality_of_service",),
            )
        ),
        minimum_nodes=_nonnegative_int(_first(record, ("minimums", "nodes"))),
        maximum_nodes=_nonnegative_int(_first(record, ("maximums", "nodes"))),
        maximum_cpus_per_node=_nonnegative_int(_first(record, ("maximums", "cpus_per_node"))),
        default_memory_mb_per_node=_memory_mb(
            _first(record, ("defaults", "partition_memory_per_node"))
        ),
        default_memory_mb_per_cpu=_memory_mb(
            _first(record, ("defaults", "partition_memory_per_cpu"))
        ),
        maximum_time_minutes=_nonnegative_int(maximum_time),
    )


def _parse_node(record: JsonObject, index: int) -> Node:
    del index
    name_value = _first(record, ("name",), ("node", "name"), ("hostname",))
    if name_value is None:
        names = _node_list(_at(record, ("nodes", "nodes")))
        name_value = names[0] if names else None
    name = _required_text(name_value, "node name")
    state_raw = _state_text(_first(record, ("state",), ("node", "state"), ("state", "current")))
    if not state_raw:
        state_raw = "UNKNOWN"

    cpu_count = (
        _nonnegative_int(
            _first(
                record,
                ("cpus", "total"),
                ("cpus", "maximum"),
                ("cpu_count",),
                ("total_cpus",),
                ("cpus",),
            )
        )
        or 0
    )
    allocated_cpus = (
        _nonnegative_int(
            _first(
                record,
                ("cpus", "allocated"),
                ("allocated_cpus",),
                ("alloc_cpus",),
            )
        )
        or 0
    )
    allocated_cpus = min(cpu_count, allocated_cpus)

    memory_mb = (
        _memory_mb(
            _first(
                record,
                ("memory", "maximum"),
                ("memory", "total"),
                ("real_memory",),
                ("memory_mb",),
            )
        )
        or 0
    )
    allocated_memory_mb = _memory_mb(
        _first(
            record,
            ("memory", "allocated"),
            ("allocated_memory",),
            ("allocated_memory_mb",),
            ("alloc_memory",),
        )
    )
    if allocated_memory_mb is not None:
        allocated_memory_mb = min(memory_mb, allocated_memory_mb)

    resources = _resource_strings(
        _first(
            record,
            ("gres", "total"),
            ("generic_resources",),
            ("gres_total",),
            ("gres",),
        )
    )
    allocated_resources = _resource_strings(
        _first(
            record,
            ("gres", "used"),
            ("allocated_generic_resources",),
            ("gres_used",),
        )
    )
    partitions = _name_list(
        _first(
            record,
            ("partitions",),
            ("partition_names",),
            ("partition", "name"),
            ("partition",),
            ("node", "partitions"),
        )
    )
    return Node(
        name=name,
        partition_names=partitions,
        state=normalize_node_state(state_raw),
        state_raw=state_raw,
        cpu_count=cpu_count,
        allocated_cpus=allocated_cpus,
        memory_mb=memory_mb,
        allocated_memory_mb=allocated_memory_mb,
        free_memory_mb=_memory_mb(_first(record, ("free_mem",), ("free_memory",))),
        cpu_load=_cpu_load(_first(record, ("cpu_load",), ("cpus", "load"))),
        sockets=_nonnegative_int(_first(record, ("sockets",))),
        cores_per_socket=_nonnegative_int(_first(record, ("cores",), ("cores_per_socket",))),
        threads_per_core=_nonnegative_int(_first(record, ("threads",), ("threads_per_core",))),
        configured_features=_name_list(_first(record, ("features",), ("configured_features",))),
        active_features=_name_list(_first(record, ("active_features",), ("features", "active"))),
        generic_resources=resources,
        allocated_generic_resources=allocated_resources,
        gpu_resources=[resource for resource in resources if _is_gpu_resource(resource)],
        reason=_reason_text(
            _first(record, ("reason", "description"), ("reason",), ("state_reason",))
        ),
    )


def _merge_partition_rows(rows: Sequence[Partition]) -> list[Partition]:
    """Merge the per-node-state rows emitted by current ``sinfo --json``."""

    grouped: dict[str, Partition] = {}
    state_parts: dict[str, list[str]] = {}
    for row in rows:
        existing = grouped.get(row.name)
        if existing is None:
            grouped[row.name] = row
            state_parts[row.name] = [row.state]
            continue

        states = state_parts[row.name]
        if row.state not in states:
            states.append(row.state)
        grouped[row.name] = Partition(
            name=row.name,
            availability=existing.availability or row.availability,
            state="+".join(states),
            time_limit=existing.time_limit or row.time_limit,
            node_count=existing.node_count + row.node_count,
            allocated_node_count=(existing.allocated_node_count + row.allocated_node_count),
            idle_node_count=existing.idle_node_count + row.idle_node_count,
            other_node_count=existing.other_node_count + row.other_node_count,
            is_default=existing.is_default or row.is_default,
            node_names=list(dict.fromkeys([*existing.node_names, *row.node_names])),
            qos=list(dict.fromkeys([*existing.qos, *row.qos])),
            minimum_nodes=existing.minimum_nodes or row.minimum_nodes,
            maximum_nodes=existing.maximum_nodes or row.maximum_nodes,
            maximum_cpus_per_node=(existing.maximum_cpus_per_node or row.maximum_cpus_per_node),
            default_memory_mb_per_node=(
                existing.default_memory_mb_per_node or row.default_memory_mb_per_node
            ),
            default_memory_mb_per_cpu=(
                existing.default_memory_mb_per_cpu or row.default_memory_mb_per_cpu
            ),
            maximum_time_minutes=(existing.maximum_time_minutes or row.maximum_time_minutes),
        )
    return list(grouped.values())


def _parse_job(record: JsonObject, source: str, index: int) -> Job:
    del index
    job_id = _job_id(record)
    (
        array_job_id,
        array_task_id,
        heterogeneous_job_id,
        heterogeneous_job_offset,
    ) = _job_scope(record, job_id)
    job_name = _required_text(
        _first(record, ("name",), ("job_name",), ("job", "name")),
        "job name",
    )
    user = _required_text(
        _first(
            record,
            ("user_name",),
            ("user", "name"),
            ("user",),
            ("username",),
        ),
        "job user",
    )
    partition = (
        _optional_text(
            _first(
                record,
                ("partition", "name"),
                ("partition",),
                ("partition_name",),
            )
        )
        or ""
    )
    state_value = _first(
        record,
        ("state", "current"),
        ("job_state",),
        ("state",),
        ("state_current",),
    )
    state_raw = _state_text(state_value) or "UNKNOWN"
    state = normalize_job_state(state_raw)

    nodes = (
        _nonnegative_int(
            _first(
                record,
                ("allocation_nodes",),
                ("node_count",),
                ("nodes", "count"),
                ("nodes", "total"),
                ("required", "nodes"),
                ("nodes",),
            )
        )
        or 0
    )
    node_list = _node_list(
        _first(
            record,
            ("node_list",),
            ("nodes", "list"),
            ("nodes", "names"),
            ("allocated_nodes",),
            ("nodes",),
        )
    )
    requested_cpus = (
        _nonnegative_int(
            _first(
                record,
                ("required", "CPUs"),
                ("required", "cpus"),
                ("requested_cpus",),
                ("allocation_cpus",),
                ("cpus", "number"),
                ("cpus", "total"),
                ("cpus",),
            )
        )
        or 0
    )
    requested_memory_mb = _requested_memory_mb(record, requested_cpus, nodes)
    requested_gpus = _requested_gpu_count(record)

    submit_time = _timestamp(
        _first(
            record,
            ("time", "submission"),
            ("time", "submit"),
            ("submit_time",),
            ("submission_time",),
            ("submit",),
        )
    )
    start_time = _timestamp(_first(record, ("time", "start"), ("start_time",), ("start",)))
    end_time = _timestamp(_first(record, ("time", "end"), ("end_time",), ("end",)))
    elapsed_seconds = (
        _duration_seconds(
            _first(
                record,
                ("time", "elapsed"),
                ("elapsed_seconds",),
                ("elapsed_time",),
                ("elapsed",),
                ("time_used",),
            ),
            numeric_unit="seconds",
        )
        or 0
    )
    time_limit_seconds = _duration_seconds(
        _first(
            record,
            ("time", "limit"),
            ("time_limit",),
            ("time_limit_minutes",),
            ("limit",),
        ),
        numeric_unit="minutes",
    )
    reason = _reason_text(
        _first(
            record,
            ("state", "reason"),
            ("state_reason",),
            ("reason", "description"),
            ("reason",),
        )
    )

    # A few 24.11 sacct fields use allocation-oriented aliases. The branch is
    # intentionally explicit to make future schema additions easy to audit.
    if source == "sacct" and nodes == 0 and node_list:
        nodes = len(node_list)

    return Job(
        job_id=job_id,
        array_job_id=array_job_id,
        array_task_id=array_task_id,
        heterogeneous_job_id=heterogeneous_job_id,
        heterogeneous_job_offset=heterogeneous_job_offset,
        job_name=job_name,
        user=user,
        partition=partition,
        state=state,
        state_raw=state_raw,
        reason=reason,
        nodes=nodes,
        node_list=node_list,
        requested_cpus=requested_cpus,
        requested_memory_mb=requested_memory_mb,
        requested_gpus=requested_gpus,
        submit_time=submit_time,
        start_time=start_time,
        end_time=end_time,
        elapsed_seconds=elapsed_seconds,
        time_limit_seconds=time_limit_seconds,
    )


def _job_id(record: JsonObject) -> str:
    value = _first(
        record,
        ("job_id",),
        ("job_id_raw",),
        ("id",),
        ("job", "id"),
    )
    unwrapped = _unwrap(value)
    if isinstance(unwrapped, bool) or unwrapped is None or unwrapped is _INFINITE:
        raise ValueError("job id is missing")
    if isinstance(unwrapped, int):
        return str(unwrapped)
    if isinstance(unwrapped, float):
        if unwrapped.is_integer():
            return str(int(unwrapped))
        raise ValueError("job id is not integral")
    text = _optional_text(unwrapped)
    if text is None:
        raise ValueError("job id is missing")
    return text


def _job_scope(
    record: JsonObject,
    job_id: str,
) -> tuple[str | None, str | None, str | None, int | None]:
    """Preserve identifiers that make a numeric job ID unsafe to cancel alone."""

    array_match = _ARRAY_JOB_IDENTIFIER.fullmatch(job_id)
    array_job_id = _scope_identifier(
        _first(
            record,
            ("array", "job_id"),
            ("array_job_id",),
            ("array", "job"),
        )
    )
    array_task_id = _scope_component(
        _first(
            record,
            ("array", "task"),
            ("array_task_string",),
            ("array_task_str",),
        )
    )
    if array_task_id is None:
        array_task_id = _scope_component(
            _first(
                record,
                ("array", "task_id"),
                ("array_task_id",),
            )
        )
    if array_match is not None:
        array_job_id = array_job_id or array_match.group("job_id")
        array_task_id = array_task_id or array_match.group("task_id")
    elif array_task_id is not None and array_job_id is None and job_id.isdigit():
        # Fail closed for adjacent schemas that expose the task marker without
        # a separate base ID.
        array_job_id = job_id

    heterogeneous_match = _HETEROGENEOUS_JOB_IDENTIFIER.fullmatch(job_id)
    heterogeneous_job_id = _scope_identifier(
        _first(
            record,
            ("het", "job_id"),
            ("heterogeneous", "job_id"),
            ("het_job_id",),
            ("heterogeneous_job_id",),
        )
    )
    heterogeneous_job_offset = _scope_offset(
        _first(
            record,
            ("het", "job_offset"),
            ("het", "offset"),
            ("heterogeneous", "job_offset"),
            ("heterogeneous", "offset"),
            ("het_job_offset",),
            ("heterogeneous_job_offset",),
        )
    )
    if heterogeneous_match is not None:
        heterogeneous_job_id = heterogeneous_job_id or heterogeneous_match.group("job_id")
        if heterogeneous_job_offset is None:
            heterogeneous_job_offset = int(heterogeneous_match.group("offset"))
    elif heterogeneous_job_offset is not None and heterogeneous_job_id is None and job_id.isdigit():
        # As above, an offset alone is enough to reject cancellation safely.
        heterogeneous_job_id = job_id

    return (
        array_job_id,
        array_task_id,
        heterogeneous_job_id,
        heterogeneous_job_offset,
    )


def _scope_identifier(value: object | None) -> str | None:
    text = _optional_text(value)
    if text is None or text == "0" or text in _SLURM_NO_VALUE_IDS:
        return None
    return text


def _scope_component(value: object | None) -> str | None:
    text = _optional_text(value)
    if text is None or text in _SLURM_NO_VALUE_IDS:
        return None
    return text


def _scope_offset(value: object | None) -> int | None:
    text = _scope_component(value)
    if text is None:
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _requested_memory_mb(record: JsonObject, cpus: int, nodes: int) -> int | None:
    direct = _first(
        record,
        ("requested_memory_mb",),
        ("required", "memory"),
        ("minimum_memory",),
        ("memory", "requested"),
    )
    direct_mb = _memory_mb(direct)
    if direct_mb is not None:
        return direct_mb

    per_cpu = _memory_mb(
        _first(
            record,
            ("required", "memory_per_cpu"),
            ("memory", "per_cpu"),
            ("memory_per_cpu",),
        )
    )
    if per_cpu is not None:
        return per_cpu * max(cpus, 1)

    per_node = _memory_mb(
        _first(
            record,
            ("required", "memory_per_node"),
            ("memory", "per_node"),
            ("memory_per_node",),
        )
    )
    if per_node is not None:
        return per_node * max(nodes, 1)
    return None


def _requested_gpu_count(record: JsonObject) -> int | None:
    direct = _nonnegative_int(_first(record, ("requested_gpus",), ("gpus", "requested"), ("gpus",)))
    if direct is not None:
        return direct

    candidates = (
        _at(record, ("tres", "requested")),
        _at(record, ("required", "tres")),
        record.get("tres_per_job"),
        record.get("tres_per_node"),
        record.get("requested_gres"),
        record.get("gres"),
    )
    for candidate in candidates:
        count = _gpu_count(candidate)
        if count is not None:
            return count
    return None


def _parse_accounting(
    allocation: JsonObject,
    steps: Sequence[JsonObject],
) -> AccountingInfo | None:
    allocation_cpu = _accounting_cpu_seconds(allocation)
    step_cpus = [value for step in steps if (value := _accounting_cpu_seconds(step)) is not None]
    elapsed_cpu_seconds = allocation_cpu
    if elapsed_cpu_seconds is None and step_cpus:
        elapsed_cpu_seconds = sum(step_cpus)

    rss_values = [
        value
        for record in (allocation, *steps)
        if (value := _accounting_max_rss_mb(record)) is not None
    ]
    max_rss_mb = max(rss_values) if rss_values else None

    allocation_energy = _accounting_energy(allocation)
    step_energies = [value for step in steps if (value := _accounting_energy(step)) is not None]
    consumed_energy_joules = allocation_energy
    if consumed_energy_joules is None and step_energies:
        consumed_energy_joules = sum(step_energies)

    if elapsed_cpu_seconds is None and max_rss_mb is None and consumed_energy_joules is None:
        return None
    return AccountingInfo(
        elapsed_cpu_seconds=elapsed_cpu_seconds,
        max_rss_mb=max_rss_mb,
        consumed_energy_joules=consumed_energy_joules,
    )


def _accounting_cpu_seconds(record: JsonObject) -> int | None:
    direct = _duration_seconds(
        _first(
            record,
            ("accounting", "elapsed_cpu_seconds"),
            ("elapsed_cpu_seconds",),
            ("time", "total_cpu"),
            ("total_cpu",),
        ),
        numeric_unit="seconds",
    )
    if direct is not None:
        return direct
    user = _duration_seconds(
        _first(record, ("time", "user"), ("user_cpu",)),
        numeric_unit="seconds",
    )
    system = _duration_seconds(
        _first(record, ("time", "system"), ("system_cpu",)),
        numeric_unit="seconds",
    )
    if user is None and system is None:
        return None
    return (user or 0) + (system or 0)


def _accounting_max_rss_mb(record: JsonObject) -> int | None:
    direct = _memory_mb(
        _first(
            record,
            ("accounting", "max_rss_mb"),
            ("max_rss_mb",),
            ("memory", "max_rss"),
            ("max_rss",),
        )
    )
    if direct is not None:
        return direct
    for candidate in (
        _at(record, ("tres", "usage", "in_max")),
        _at(record, ("tres", "usage", "max")),
    ):
        value = _tres_value(candidate, {"mem", "memory"})
        if value is not None:
            return value
    return None


def _accounting_energy(record: JsonObject) -> int | None:
    direct = _nonnegative_int(
        _first(
            record,
            ("accounting", "consumed_energy_joules"),
            ("consumed_energy_joules",),
            ("consumed_energy_raw",),
            ("energy", "consumed"),
        )
    )
    if direct is not None:
        return direct
    return _tres_value(
        _at(record, ("tres", "usage", "in_total")),
        {"energy"},
    )


def _tres_value(value: object | None, accepted_names: set[str]) -> int | None:
    sequence = _as_sequence(value)
    if sequence is None:
        return None
    for entry_value in sequence:
        entry = _as_object(entry_value)
        if entry is None:
            continue
        entry_type = (_optional_text(entry.get("type")) or "").casefold()
        entry_name = (_optional_text(entry.get("name")) or "").casefold()
        if entry_type in accepted_names or entry_name in accepted_names:
            return _nonnegative_int(entry.get("count"))
    return None


def _exit_code(value: object | None) -> str | None:
    unwrapped = _unwrap(value)
    if unwrapped is None or unwrapped is _INFINITE:
        return None
    mapping = _as_object(unwrapped)
    if mapping is not None:
        return_code = _nonnegative_int(
            _first(mapping, ("return_code",), ("status_code",), ("code",))
        )
        signal_value = _first(mapping, ("signal", "id"), ("signal",), ("signal_id",))
        signal = _nonnegative_int(signal_value) or 0
        if return_code is None:
            return None
        return f"{return_code}:{signal}"
    number = _nonnegative_int(unwrapped)
    if number is not None:
        return f"{number}:0"
    text = _optional_text(unwrapped)
    return text


def _partition_time_limit(value: object | None) -> str | None:
    unwrapped = _unwrap(value)
    if unwrapped is _INFINITE:
        return "UNLIMITED"
    minutes = _nonnegative_int(unwrapped)
    if minutes is None:
        text = _optional_text(unwrapped)
        return text
    seconds = minutes * 60
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minute_count, second_count = divmod(remainder, 60)
    clock = f"{hours:02d}:{minute_count:02d}:{second_count:02d}"
    return f"{days}-{clock}" if days else clock


def _duration_seconds(value: object | None, *, numeric_unit: str) -> int | None:
    unwrapped = _unwrap(value)
    if unwrapped is None or unwrapped is _INFINITE or isinstance(unwrapped, bool):
        return None
    if isinstance(unwrapped, (int, float)):
        if unwrapped < 0:
            return None
        multiplier = 60 if numeric_unit == "minutes" else 1
        return int(unwrapped * multiplier)
    text = _optional_text(unwrapped)
    if text is None:
        return None
    if text.isdigit():
        multiplier = 60 if numeric_unit == "minutes" else 1
        return int(text) * multiplier
    return parse_slurm_duration(text)


def _timestamp(value: object | None) -> datetime | None:
    unwrapped = _unwrap(value)
    if unwrapped is None or unwrapped is _INFINITE or isinstance(unwrapped, bool):
        return None
    if isinstance(unwrapped, (int, float)):
        if unwrapped <= 0:
            return None
        try:
            return datetime.fromtimestamp(unwrapped, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    return parse_slurm_timestamp(_optional_text(unwrapped))


def _memory_mb(value: object | None) -> int | None:
    unwrapped = _unwrap(value)
    if unwrapped is None or unwrapped is _INFINITE or isinstance(unwrapped, bool):
        return None
    if isinstance(unwrapped, (int, float)):
        return int(unwrapped) if unwrapped >= 0 else None
    return parse_slurm_memory_mb(_optional_text(unwrapped))


def _gpu_count(value: object | None) -> int | None:
    unwrapped = _unwrap(value)
    if unwrapped is None or unwrapped is _INFINITE:
        return None
    sequence = _as_sequence(unwrapped)
    if sequence is None:
        return parse_slurm_gpu_count(_optional_text(unwrapped))

    aggregate: int | None = None
    typed_total = 0
    saw_gpu = False
    for entry_value in sequence:
        entry = _as_object(entry_value)
        if entry is None:
            text_count = parse_slurm_gpu_count(_optional_text(entry_value))
            if text_count is not None:
                typed_total += text_count
                saw_gpu = True
            continue
        entry_type = (_optional_text(entry.get("type")) or "").casefold()
        entry_name = (_optional_text(entry.get("name")) or "").casefold()
        resource_name = "/".join(part for part in (entry_type, entry_name) if part)
        if "gpu" not in resource_name:
            continue
        count = _nonnegative_int(entry.get("count"))
        if count is None:
            continue
        saw_gpu = True
        if resource_name in {"gpu", "gres/gpu"}:
            aggregate = count
        else:
            typed_total += count
    if aggregate is not None:
        return aggregate
    return typed_total if saw_gpu else None


def _resource_strings(value: object | None) -> list[str]:
    unwrapped = _unwrap(value)
    if unwrapped is None or unwrapped is _INFINITE:
        return []
    sequence = _as_sequence(unwrapped)
    if sequence is None:
        return parse_slurm_resource_list(_optional_text(unwrapped))

    resources: list[str] = []
    for item in sequence:
        mapping = _as_object(item)
        if mapping is None:
            text = _optional_text(item)
            if text is not None and text not in resources:
                resources.append(text)
            continue
        resource_type = _optional_text(mapping.get("type")) or ""
        name = _optional_text(mapping.get("name")) or ""
        count = _nonnegative_int(mapping.get("count"))
        if resource_type.casefold() == "gres":
            prefix = name
        elif name:
            prefix = f"{resource_type}:{name}" if resource_type else name
        else:
            prefix = resource_type
        if not prefix:
            continue
        rendered = f"{prefix}:{count}" if count is not None else prefix
        if rendered not in resources:
            resources.append(rendered)
    return resources


def _node_list(value: object | None) -> list[str]:
    unwrapped = _unwrap(value)
    if unwrapped is None or unwrapped is _INFINITE:
        return []
    sequence = _as_sequence(unwrapped)
    if sequence is None:
        return parse_slurm_node_list(_optional_text(unwrapped))

    names: list[str] = []
    for item in sequence:
        mapping = _as_object(item)
        text = (
            _optional_text(_first(mapping, ("name",), ("hostname",)))
            if mapping is not None
            else _optional_text(item)
        )
        if text is not None and text not in names:
            names.append(text)
    return names


def _name_list(value: object | None) -> list[str]:
    return [name.removesuffix("*") for name in _node_list(value) if name.removesuffix("*")]


def _state_text(value: object | None) -> str:
    unwrapped = _unwrap(value)
    mapping = _as_object(unwrapped)
    if mapping is not None:
        return _state_text(_first(mapping, ("current",), ("state",), ("name",), ("description",)))
    sequence = _as_sequence(unwrapped)
    if sequence is not None:
        components = [
            component
            for item in sequence
            if (component := _optional_text(_unwrap(item))) is not None
        ]
        return "+".join(components)
    return _optional_text(unwrapped) or ""


def _reason_text(value: object | None) -> str | None:
    mapping = _as_object(value)
    if mapping is not None:
        value = _first(mapping, ("description",), ("reason",), ("name",))
    text = _optional_text(_unwrap(value))
    if text is None:
        return None
    if text.startswith("(") and text.endswith(")") and len(text) > 2:
        text = text[1:-1].strip()
    return text or None


def _required_text(value: object | None, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} is missing")
    return text


def _optional_text(value: object | None) -> str | None:
    unwrapped = _unwrap(value)
    if unwrapped is None or unwrapped is _INFINITE or isinstance(unwrapped, bool):
        return None
    mapping = _as_object(unwrapped)
    if mapping is not None:
        return _optional_text(_first(mapping, ("name",), ("description",), ("string",), ("value",)))
    if isinstance(unwrapped, float) and unwrapped.is_integer():
        text = str(int(unwrapped))
    else:
        text = str(unwrapped)
    text = text.strip()
    return None if text.casefold() in _MISSING_TEXT else text


def _nonnegative_int(value: object | None) -> int | None:
    unwrapped = _unwrap(value)
    if unwrapped is None or unwrapped is _INFINITE or isinstance(unwrapped, bool):
        return None
    if isinstance(unwrapped, int):
        return unwrapped if unwrapped >= 0 else None
    if isinstance(unwrapped, float):
        return int(unwrapped) if unwrapped >= 0 and unwrapped.is_integer() else None
    text = _optional_text(unwrapped)
    if text is None:
        return None
    try:
        parsed = int(text)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _cpu_load(value: object | None) -> float | None:
    unwrapped = _unwrap(value)
    if isinstance(unwrapped, int) and not isinstance(unwrapped, bool):
        return max(0.0, unwrapped / 100)
    if isinstance(unwrapped, float):
        return unwrapped if unwrapped >= 0 else None
    text = _optional_text(unwrapped)
    if text is None:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _unwrap(value: object | None) -> object | None:
    mapping = _as_object(value)
    if mapping is None:
        return value

    is_set = mapping.get("set")
    if isinstance(is_set, bool) and not is_set:
        return None
    is_infinite = mapping.get("infinite")
    if isinstance(is_infinite, bool) and is_infinite:
        return _INFINITE
    for key in ("number", "value", "seconds", "minutes", "id"):
        if key in mapping:
            return _unwrap(mapping[key])
    return mapping


def _first(record: JsonObject | None, *paths: JsonPath) -> object | None:
    if record is None:
        return None
    for path in paths:
        value = _at(record, path)
        if value is not None:
            return value
    return None


def _at(record: JsonObject, path: JsonPath) -> object | None:
    current: object = record
    for part in path:
        mapping = _as_object(current)
        if mapping is None or part not in mapping:
            return None
        current = mapping[part]
    return current


def _as_object(value: object | None) -> JsonObject | None:
    if not isinstance(value, dict):
        return None
    return cast(dict[str, object], value)


def _as_sequence(value: object | None) -> list[object] | None:
    if not isinstance(value, list):
        return None
    return cast(list[object], value)


def _is_gpu_resource(resource: str) -> bool:
    normalized = resource.casefold()
    return normalized == "gpu" or normalized.startswith(("gpu:", "gres/gpu"))


def _is_step_id(job_id: str) -> bool:
    return "." in job_id or job_id.casefold().endswith(_TERMINAL_STEP_SUFFIXES)


def _belongs_to_job_step(record_id: str, job_id: str) -> bool:
    return record_id.startswith(f"{job_id}.")


def _job_sort_key(job: Job) -> tuple[float, str]:
    selected = job.end_time or job.start_time or job.submit_time
    if selected is None:
        return (0.0, job.job_id)
    if selected.tzinfo is None:
        selected = selected.replace(tzinfo=UTC)
    return (selected.timestamp(), job.job_id)
