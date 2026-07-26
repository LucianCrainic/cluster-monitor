"""Parsers for explicit, pipe-delimited Slurm fallback output.

These parsers intentionally do not understand Slurm's human-oriented tables.
Callers must request one of the fixed layouts below with headers disabled:

* ``PARTITION_SINFO_FORMAT``:
  ``name|availability|time_limit|node_count|allocated/idle/other/total``
* ``NODE_SINFO_FORMAT``:
  ``name|partitions|state|cpus|allocated/idle/other/total CPUs|memory|free memory|GRES|reason``
* ``SQUEUE_JOB_FORMAT`` (for ``squeue --Format``, with a capital F):
  explicit identity, scope, resource, timing, and state fields for active jobs
* ``SACCT_JOB_FIELDS``:
  the named fields in that tuple, emitted by ``sacct --parsable2 --noheader``.

The final field is free text in every layout that has one. A pipe in that final
field is therefore preserved rather than being mistaken for another column.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from cluster_monitor.models import Job, JobState, Node, Partition
from cluster_monitor.slurm.normalization import normalize_job_state, normalize_node_state

PARTITION_FIELDS = (
    "name",
    "availability",
    "time_limit",
    "node_count",
    "node_allocation",
)
PARTITION_SINFO_FORMAT = "%P|%a|%l|%D|%F"

NODE_FIELDS = (
    "name",
    "partitions",
    "state",
    "cpu_count",
    "cpu_allocation",
    "memory",
    "free_memory",
    "generic_resources",
    "reason",
)
NODE_SINFO_FORMAT = "%N|%P|%T|%c|%C|%m|%e|%G|%E"

SQUEUE_JOB_FIELDS = (
    "job_id",
    "array_job_id",
    "array_task_id",
    "heterogeneous_job_id",
    "heterogeneous_job_offset",
    "job_name",
    "user",
    "partition",
    "state",
    "nodes",
    "node_list",
    "requested_cpus",
    "requested_memory",
    "requested_gres",
    "submit_time",
    "start_time",
    "elapsed",
    "time_limit",
    "reason",
)
SQUEUE_JOB_FORMAT = (
    "JobID:1|,ArrayJobID:1|,ArrayTaskID:1|,HetJobID:1|,HetJobOffset:1|,"
    "Name:1|,UserName:1|,Partition:1|,State:1|,"
    "NumNodes:1|,NodeList:1|,NumCPUs:1|,MinMemory:1|,tres-alloc:1|,"
    "SubmitTime:1|,StartTime:1|,TimeUsed:1|,TimeLimit:1|,Reason:1"
)

SACCT_JOB_FIELDS = (
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

_MISSING_VALUES = frozenset(
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
_NO_LIMIT_VALUES = frozenset({"infinite", "unlimited", "partition_limit"})
_MEMORY_PATTERN = re.compile(
    r"""
    ^\s*
    (?P<amount>\d+(?:\.\d+)?)
    \s*
    (?P<unit>[kmgtpe](?:i?b)?|b)?
    (?P<scope>[cn])?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_INTEGER_PATTERN = re.compile(r"^\+?\d+$")
_ARRAY_JOB_IDENTIFIER = re.compile(r"^(?P<job_id>[1-9][0-9]*)_(?P<task_id>.+)$")
_HETEROGENEOUS_JOB_IDENTIFIER = re.compile(r"^(?P<job_id>[1-9][0-9]*)\+(?P<offset>[0-9]+)$")
_SLURM_NO_VALUE_IDS = frozenset({"4294967294", "4294967295"})
_GPU_TRES_PATTERN = re.compile(
    r"^gres/gpu(?::[^=,]+)?=(?P<count>\d+)(?:\.\d+)?$",
    re.IGNORECASE,
)
_GPU_GRES_PATTERN = re.compile(r"^gpu(?::.*)?$", re.IGNORECASE)


class SlurmTextParseError(ValueError):
    """A fixed-format Slurm record did not contain the expected fields."""

    def __init__(
        self,
        record_kind: str,
        line_number: int,
        expected_fields: int,
        actual_fields: int,
    ) -> None:
        super().__init__(
            f"invalid {record_kind} record on line {line_number}: "
            f"expected {expected_fields} fields, got {actual_fields}"
        )
        self.record_kind = record_kind
        self.line_number = line_number
        self.expected_fields = expected_fields
        self.actual_fields = actual_fields


def parse_partitions_text(output: str) -> list[Partition]:
    """Parse ``sinfo`` output produced with ``PARTITION_SINFO_FORMAT``."""

    partitions: list[Partition] = []
    for row in _iter_rows(output, PARTITION_FIELDS, "partition"):
        allocation = _parse_allocation(row["node_allocation"])
        reported_node_count = _parse_nonnegative_int(row["node_count"])
        node_count = reported_node_count if reported_node_count is not None else allocation[3]
        name = _require_value(row["name"], "partition name").removesuffix("*")
        availability_raw = row["availability"].strip()
        partitions.append(
            Partition(
                name=name,
                availability=_parse_availability(availability_raw),
                state=availability_raw.upper() or "UNKNOWN",
                time_limit=_optional_text(row["time_limit"]),
                node_count=node_count,
                allocated_node_count=allocation[0],
                idle_node_count=allocation[1],
                other_node_count=allocation[2],
            )
        )
    return partitions


def parse_nodes_text(output: str) -> list[Node]:
    """Parse ``sinfo -N`` output produced with ``NODE_SINFO_FORMAT``.

    Slurm's fallback ``sinfo`` layout exposes free rather than allocated
    memory. When both total and free memory are known, the model's allocated
    memory field contains the bounded ``total - free`` estimate. It remains
    ``None`` when the cluster does not report free memory.
    """

    nodes_by_name: dict[str, Node] = {}
    for row in _iter_rows(output, NODE_FIELDS, "node"):
        cpu_allocation = _parse_allocation(row["cpu_allocation"])
        reported_cpu_count = _parse_nonnegative_int(row["cpu_count"])
        cpu_count = reported_cpu_count if reported_cpu_count is not None else cpu_allocation[3]
        memory_mb = parse_slurm_memory_mb(row["memory"]) or 0
        free_memory_mb = parse_slurm_memory_mb(row["free_memory"])
        allocated_memory_mb = (
            None if free_memory_mb is None else min(memory_mb, max(0, memory_mb - free_memory_mb))
        )
        state_raw = row["state"].strip() or "UNKNOWN"
        generic_resources = parse_slurm_resource_list(row["generic_resources"])
        name = _require_value(row["name"], "node name")
        parsed_node = Node(
            name=name,
            partition_names=_parse_partition_names(row["partitions"]),
            state=normalize_node_state(state_raw),
            state_raw=state_raw,
            cpu_count=cpu_count,
            allocated_cpus=min(cpu_count, cpu_allocation[0]),
            memory_mb=memory_mb,
            allocated_memory_mb=allocated_memory_mb,
            generic_resources=generic_resources,
            gpu_resources=[
                resource
                for resource in generic_resources
                if _GPU_GRES_PATTERN.fullmatch(_resource_without_topology(resource))
            ],
            reason=_parse_reason(row["reason"]),
        )
        existing = nodes_by_name.get(name)
        nodes_by_name[name] = (
            parsed_node if existing is None else _merge_node_partitions(existing, parsed_node)
        )
    return list(nodes_by_name.values())


def parse_squeue_jobs_text(output: str) -> list[Job]:
    """Parse ``squeue`` output produced with ``SQUEUE_JOB_FORMAT``."""

    jobs: list[Job] = []
    for row in _iter_rows(output, SQUEUE_JOB_FIELDS, "squeue job"):
        job_id = _require_value(row["job_id"], "job id")
        (
            array_job_id,
            array_task_id,
            heterogeneous_job_id,
            heterogeneous_job_offset,
        ) = _job_scope(
            job_id,
            array_job_id=row["array_job_id"],
            array_task_id=row["array_task_id"],
            heterogeneous_job_id=row["heterogeneous_job_id"],
            heterogeneous_job_offset=row["heterogeneous_job_offset"],
        )
        nodes = _parse_nonnegative_int(row["nodes"]) or 0
        requested_cpus = _parse_nonnegative_int(row["requested_cpus"]) or 0
        state_raw = row["state"].strip() or "UNKNOWN"
        state = normalize_job_state(state_raw)
        node_list = parse_slurm_node_list(row["node_list"])
        jobs.append(
            Job(
                job_id=job_id,
                array_job_id=array_job_id,
                array_task_id=array_task_id,
                heterogeneous_job_id=heterogeneous_job_id,
                heterogeneous_job_offset=heterogeneous_job_offset,
                job_name=_require_value(row["job_name"], "job name"),
                user=_require_value(row["user"], "job user"),
                partition=_optional_text(row["partition"]) or "",
                state=state,
                state_raw=state_raw,
                reason=_job_reason(row["reason"], node_list, state),
                nodes=nodes,
                node_list=node_list,
                requested_cpus=requested_cpus,
                requested_memory_mb=parse_slurm_memory_mb(
                    row["requested_memory"],
                    cpus=requested_cpus,
                    nodes=nodes,
                ),
                requested_gpus=parse_slurm_gpu_count(row["requested_gres"]),
                submit_time=parse_slurm_timestamp(row["submit_time"]),
                start_time=parse_slurm_timestamp(row["start_time"]),
                elapsed_seconds=parse_slurm_duration(row["elapsed"]) or 0,
                time_limit_seconds=parse_slurm_duration(row["time_limit"]),
            )
        )
    return jobs


def parse_sacct_jobs_text(output: str) -> list[Job]:
    """Parse allocation rows from pipe-delimited ``sacct`` output.

    Job-step rows are ignored defensively. Callers should still request
    allocations only (``sacct --allocations``) to avoid unnecessary output.
    """

    jobs: list[Job] = []
    for row in _iter_rows(output, SACCT_JOB_FIELDS, "sacct job"):
        job_id = _require_value(row["JobIDRaw"], "job id")
        if "." in job_id:
            continue
        (
            array_job_id,
            array_task_id,
            heterogeneous_job_id,
            heterogeneous_job_offset,
        ) = _job_scope(_require_value(row["JobID"], "formatted job id"))
        nodes = _parse_nonnegative_int(row["NNodes"]) or 0
        requested_cpus = _parse_nonnegative_int(row["ReqCPUS"]) or 0
        state_raw = row["State"].strip() or "UNKNOWN"
        state = normalize_job_state(state_raw)
        node_list = parse_slurm_node_list(row["NodeList"])
        jobs.append(
            Job(
                job_id=job_id,
                array_job_id=array_job_id,
                array_task_id=array_task_id,
                heterogeneous_job_id=heterogeneous_job_id,
                heterogeneous_job_offset=heterogeneous_job_offset,
                job_name=_require_value(row["JobName"], "job name"),
                user=_require_value(row["User"], "job user"),
                partition=_optional_text(row["Partition"]) or "",
                state=state,
                state_raw=state_raw,
                reason=_job_reason(row["Reason"], node_list, state),
                nodes=nodes,
                node_list=node_list,
                requested_cpus=requested_cpus,
                requested_memory_mb=parse_slurm_memory_mb(
                    row["ReqMem"],
                    cpus=requested_cpus,
                    nodes=nodes,
                ),
                requested_gpus=parse_slurm_gpu_count(row["ReqTRES"]),
                submit_time=parse_slurm_timestamp(row["Submit"]),
                start_time=parse_slurm_timestamp(row["Start"]),
                end_time=parse_slurm_timestamp(row["End"]),
                elapsed_seconds=parse_slurm_duration(row["Elapsed"]) or 0,
                time_limit_seconds=parse_slurm_duration(row["Timelimit"]),
            )
        )
    return jobs


def parse_slurm_duration(value: str | None) -> int | None:
    """Return seconds for a Slurm ``[days-]HH:MM:SS`` duration.

    Two-component values are treated as ``MM:SS``. Fractional seconds are
    discarded because the public model stores whole seconds.
    """

    text = _optional_text(value)
    if text is None or text.casefold() in _NO_LIMIT_VALUES:
        return None

    day_count = 0
    clock = text
    if "-" in text:
        day_text, separator, clock = text.partition("-")
        if not separator or not _INTEGER_PATTERN.fullmatch(day_text):
            return None
        day_count = int(day_text)

    parts = clock.split(":")
    if not 1 <= len(parts) <= 3:
        return None

    whole_parts: list[int] = []
    for index, part in enumerate(parts):
        whole = part
        if index == len(parts) - 1 and "." in part:
            whole, decimal_point, fraction = part.partition(".")
            if decimal_point and (not fraction or not fraction.isdigit()):
                return None
        if not _INTEGER_PATTERN.fullmatch(whole):
            return None
        whole_parts.append(int(whole))

    if len(whole_parts) == 3:
        hours, minutes, seconds = whole_parts
    elif len(whole_parts) == 2:
        hours = 0
        minutes, seconds = whole_parts
    else:
        hours = 0
        minutes = 0
        seconds = whole_parts[0]

    if (
        (len(whole_parts) > 1 and seconds >= 60)
        or (len(whole_parts) == 3 and minutes >= 60)
        or (day_count and hours >= 24)
    ):
        return None
    return day_count * 86_400 + hours * 3_600 + minutes * 60 + seconds


def parse_slurm_memory_mb(
    value: str | None,
    *,
    cpus: int | None = None,
    nodes: int | None = None,
) -> int | None:
    """Convert a Slurm memory value to total mebibytes.

    Slurm's trailing ``c`` and ``n`` markers mean per CPU and per node. When
    the corresponding count is unavailable or zero, one unit is retained
    instead of incorrectly turning a real request into zero.
    """

    text = _optional_text(value)
    if text is None:
        return None
    match = _MEMORY_PATTERN.fullmatch(text)
    if match is None:
        return None

    try:
        amount = Decimal(match.group("amount"))
    except InvalidOperation:
        return None

    unit = (match.group("unit") or "m").casefold()
    unit = unit.removesuffix("b").removesuffix("i")
    factors = {
        "": Decimal(1) / Decimal(1024 * 1024),
        "k": Decimal(1) / Decimal(1024),
        "m": Decimal(1),
        "g": Decimal(1024),
        "t": Decimal(1024**2),
        "p": Decimal(1024**3),
        "e": Decimal(1024**4),
    }
    factor = factors.get(unit)
    if factor is None:
        return None

    scope = (match.group("scope") or "").casefold()
    multiplier = 1
    if scope == "c" and cpus is not None and cpus > 0:
        multiplier = cpus
    elif scope == "n" and nodes is not None and nodes > 0:
        multiplier = nodes

    total = amount * factor * multiplier
    return int(total.to_integral_value(rounding=ROUND_CEILING))


def parse_slurm_timestamp(value: str | None) -> datetime | None:
    """Parse Slurm ISO timestamps and known missing-value sentinels."""

    text = _optional_text(value)
    if text is None or text == "0":
        return None
    if _INTEGER_PATTERN.fullmatch(text) and len(text) >= 10:
        try:
            return datetime.fromtimestamp(int(text), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_slurm_resource_list(value: str | None) -> list[str]:
    """Split comma-separated Slurm resources without splitting topology groups."""

    text = _optional_text(value)
    if text is None:
        return []
    return _split_top_level(text)


def parse_slurm_gpu_count(value: str | None) -> int | None:
    """Extract requested GPU count from GRES or TRES syntax.

    An aggregate ``gres/gpu=N`` TRES wins over typed entries so an output such
    as ``gres/gpu=2,gres/gpu:a100=2`` is not double-counted.
    """

    text = _optional_text(value)
    if text is None:
        return None

    resources = _split_top_level(text)
    aggregate_count: int | None = None
    typed_tres_count = 0
    gres_count = 0
    saw_tres = False
    for resource in resources:
        normalized = _resource_without_topology(resource)
        tres_match = _GPU_TRES_PATTERN.fullmatch(normalized)
        if tres_match is not None:
            count = int(tres_match.group("count"))
            saw_tres = True
            if normalized.casefold().startswith("gres/gpu="):
                aggregate_count = count
            else:
                typed_tres_count += count
            continue
        if not _GPU_GRES_PATTERN.fullmatch(normalized):
            continue
        gres_count += _gpu_gres_count(normalized)

    if aggregate_count is not None:
        return aggregate_count
    if saw_tres:
        return typed_tres_count
    return gres_count


def parse_slurm_node_list(value: str | None) -> list[str]:
    """Return top-level node expressions while preserving bracketed ranges."""

    text = _optional_text(value)
    if text is None:
        return []
    return _split_top_level(text)


def _iter_rows(
    output: str,
    fields: Sequence[str],
    record_kind: str,
) -> Iterator[dict[str, str]]:
    expected_fields = len(fields)
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split("|")
        while len(parts) > expected_fields and not parts[-1]:
            parts.pop()
        if len(parts) > expected_fields:
            parts = [*parts[: expected_fields - 1], "|".join(parts[expected_fields - 1 :])]
        if len(parts) != expected_fields:
            raise SlurmTextParseError(
                record_kind,
                line_number,
                expected_fields,
                len(parts),
            )
        yield dict(zip(fields, (part.strip() for part in parts), strict=True))


def _parse_allocation(value: str) -> tuple[int, int, int, int]:
    parts = value.strip().split("/")
    if len(parts) != 4:
        return (0, 0, 0, 0)
    values = [_parse_nonnegative_int(part) for part in parts]
    if any(item is None for item in values):
        return (0, 0, 0, 0)
    allocated, idle, other, total = values
    assert allocated is not None
    assert idle is not None
    assert other is not None
    assert total is not None
    return (allocated, idle, other, total)


def _parse_nonnegative_int(value: str | None) -> int | None:
    text = _optional_text(value)
    if text is None or not _INTEGER_PATTERN.fullmatch(text):
        return None
    parsed = int(text)
    return parsed if parsed >= 0 else None


def _job_scope(
    job_id: str,
    *,
    array_job_id: str | None = None,
    array_task_id: str | None = None,
    heterogeneous_job_id: str | None = None,
    heterogeneous_job_offset: str | None = None,
) -> tuple[str | None, str | None, str | None, int | None]:
    """Normalize scope fields while avoiding ArrayJobID's non-array alias."""

    array_match = _ARRAY_JOB_IDENTIFIER.fullmatch(job_id)
    normalized_array_task_id = _scope_component(array_task_id)
    normalized_array_job_id = _scope_identifier(array_job_id)
    if array_match is not None:
        normalized_array_job_id = normalized_array_job_id or array_match.group("job_id")
        normalized_array_task_id = normalized_array_task_id or array_match.group("task_id")
    elif normalized_array_task_id is not None:
        normalized_array_job_id = normalized_array_job_id or (job_id if job_id.isdigit() else None)
    else:
        # Squeue's ArrayJobID field equals JobID for ordinary jobs.
        normalized_array_job_id = None

    heterogeneous_match = _HETEROGENEOUS_JOB_IDENTIFIER.fullmatch(job_id)
    normalized_heterogeneous_job_id = _scope_identifier(heterogeneous_job_id)
    normalized_heterogeneous_job_offset = _scope_offset(heterogeneous_job_offset)
    if heterogeneous_match is not None:
        normalized_heterogeneous_job_id = (
            normalized_heterogeneous_job_id or heterogeneous_match.group("job_id")
        )
        if normalized_heterogeneous_job_offset is None:
            normalized_heterogeneous_job_offset = int(heterogeneous_match.group("offset"))
    elif (
        normalized_heterogeneous_job_offset is not None
        and normalized_heterogeneous_job_id is None
        and job_id.isdigit()
    ):
        normalized_heterogeneous_job_id = job_id

    return (
        normalized_array_job_id,
        normalized_array_task_id,
        normalized_heterogeneous_job_id,
        normalized_heterogeneous_job_offset,
    )


def _scope_identifier(value: str | None) -> str | None:
    text = _optional_text(value)
    if text is None or text == "0" or text in _SLURM_NO_VALUE_IDS:
        return None
    return text


def _scope_component(value: str | None) -> str | None:
    text = _optional_text(value)
    if text is None or text in _SLURM_NO_VALUE_IDS:
        return None
    return text


def _scope_offset(value: str | None) -> int | None:
    text = _scope_component(value)
    if text is None or not _INTEGER_PATTERN.fullmatch(text):
        return None
    return int(text)


def _parse_availability(value: str) -> bool:
    return value.strip().casefold() in {"up", "yes", "available", "active"}


def _parse_partition_names(value: str) -> list[str]:
    names: list[str] = []
    for raw_name in _split_top_level(value):
        name = raw_name.removesuffix("*").strip()
        if name and name not in names:
            names.append(name)
    return names


def _merge_node_partitions(existing: Node, duplicate: Node) -> Node:
    return existing.model_copy(
        update={
            "partition_names": _unique([*existing.partition_names, *duplicate.partition_names]),
            "generic_resources": _unique(
                [*existing.generic_resources, *duplicate.generic_resources]
            ),
            "gpu_resources": _unique([*existing.gpu_resources, *duplicate.gpu_resources]),
            "reason": existing.reason or duplicate.reason,
        }
    )


def _parse_reason(value: str | None) -> str | None:
    reason = _optional_text(value)
    if reason is None:
        return None
    if reason.startswith("(") and reason.endswith(")") and len(reason) > 2:
        reason = reason[1:-1].strip()
    return reason or None


def _job_reason(
    value: str | None,
    node_list: Sequence[str],
    state: JobState,
) -> str | None:
    reason = _parse_reason(value)
    if reason is None:
        return None
    if state is JobState.RUNNING and (
        reason in node_list or parse_slurm_node_list(reason) == list(node_list)
    ):
        return None
    return reason


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return None if text.casefold() in _MISSING_VALUES else text


def _require_value(value: str | None, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _resource_without_topology(value: str) -> str:
    return value.partition("(")[0].strip()


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _gpu_gres_count(value: str) -> int:
    components = value.split(":")
    for component in reversed(components[1:]):
        if component.isdigit():
            return int(component)
    return 1


def _split_top_level(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    square_depth = 0
    round_depth = 0
    for index, character in enumerate(value):
        if character == "[":
            square_depth += 1
        elif character == "]":
            square_depth = max(0, square_depth - 1)
        elif character == "(":
            round_depth += 1
        elif character == ")":
            round_depth = max(0, round_depth - 1)
        elif character == "," and square_depth == 0 and round_depth == 0:
            part = value[start:index].strip()
            if part:
                parts.append(part)
            start = index + 1
    final = value[start:].strip()
    if final:
        parts.append(final)
    return parts
