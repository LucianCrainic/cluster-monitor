"""Safe parsing and normalization of Slurm job-log metadata."""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any, cast

from cluster_monitor.models import JobDetails, JobState
from cluster_monitor.slurm.normalization import normalize_job_state

_LOG_JOB_ID = re.compile(r"^(?P<job>[1-9][0-9]*)(?:_(?P<task>[0-9]+))?$")
_SCONTROL_FIELD = re.compile(r"(?:^| )(?P<key>[A-Za-z][A-Za-z0-9_]*)=")
_PATTERN = re.compile(r"%(?P<width>[0-9]*)(?P<token>[%Aajux])")
_NO_VALUE = {"", "none", "n/a", "(null)", "unknown"}
_MAX_PATH_BYTES = 4096


class JobLogMetadataParseError(ValueError):
    """Slurm returned log metadata that could not be normalized safely."""


@dataclass(frozen=True, slots=True)
class JobLogMetadata:
    job_id: str
    user: str
    state: JobState
    state_raw: str
    job_name: str
    working_directory: str | None
    stdout_path: str | None
    stderr_path: str | None
    array_job_id: str | None = None
    array_task_id: str | None = None
    heterogeneous_job_id: str | None = None
    heterogeneous_job_offset: str | None = None
    patterns_expanded: bool = False

    @property
    def terminal(self) -> bool:
        return self.state in {
            JobState.COMPLETED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.TIMEOUT,
            JobState.OUT_OF_MEMORY,
        }

    @property
    def ambiguous_array_leader(self) -> bool:
        return "_" not in self.job_id and self.array_job_id is not None


def validate_log_job_id(job_id: str) -> None:
    if _LOG_JOB_ID.fullmatch(job_id) is None:
        raise ValueError("unsupported Slurm log job identifier")


def metadata_from_job_details(details: JobDetails) -> JobLogMetadata:
    return JobLogMetadata(
        job_id=details.job_id,
        user=details.user,
        state=details.state,
        state_raw=details.state_raw,
        job_name=details.job_name,
        working_directory=details.working_directory,
        stdout_path=details.standard_output_path,
        stderr_path=details.standard_error_path,
        array_job_id=details.array_job_id,
        array_task_id=details.array_task_id,
        heterogeneous_job_id=details.heterogeneous_job_id,
        heterogeneous_job_offset=(
            str(details.heterogeneous_job_offset)
            if details.heterogeneous_job_offset is not None
            else None
        ),
        patterns_expanded=True,
    )


def overlay_metadata(primary: JobLogMetadata, expanded: JobLogMetadata) -> JobLogMetadata:
    """Overlay sacct's expanded paths without discarding live scontrol state."""

    return replace(
        primary,
        working_directory=expanded.working_directory or primary.working_directory,
        stdout_path=expanded.stdout_path or primary.stdout_path,
        stderr_path=expanded.stderr_path or primary.stderr_path,
        array_job_id=expanded.array_job_id or primary.array_job_id,
        array_task_id=expanded.array_task_id or primary.array_task_id,
        heterogeneous_job_id=expanded.heterogeneous_job_id or primary.heterogeneous_job_id,
        heterogeneous_job_offset=(
            expanded.heterogeneous_job_offset or primary.heterogeneous_job_offset
        ),
        patterns_expanded=expanded.patterns_expanded,
    )


def parse_scontrol_job_logs_json(output: str, requested_job_id: str) -> JobLogMetadata | None:
    try:
        payload: object = json.loads(output)
    except json.JSONDecodeError as exc:
        raise JobLogMetadataParseError("scontrol did not return valid JSON") from exc
    if not isinstance(payload, dict):
        raise JobLogMetadataParseError("scontrol JSON root is not an object")
    records = payload.get("jobs")
    if not isinstance(records, list):
        return None
    for raw_record in records:
        if not isinstance(raw_record, dict):
            continue
        record = _metadata_from_mapping(raw_record, requested_job_id)
        if record is not None:
            return record
    return None


def parse_scontrol_job_logs_text(output: str, requested_job_id: str) -> JobLogMetadata | None:
    for line in output.splitlines():
        fields = _scontrol_fields(line.strip())
        if not fields:
            continue
        record = _metadata_from_mapping(fields, requested_job_id)
        if record is not None:
            return record
    return None


def parse_sacct_job_logs_text(output: str, requested_job_id: str) -> JobLogMetadata | None:
    for line in output.splitlines():
        values = line.rstrip("|").split("|")
        if len(values) < 8:
            continue
        raw_id, display_id, user, state, workdir, stdout, stderr, name, *scope = values
        if requested_job_id not in {raw_id, display_id}:
            continue
        array_job_id = _scope_id(scope[0], zero_is_missing=True) if len(scope) > 0 else None
        array_task_id = _scope_id(scope[1]) if len(scope) > 1 else None
        heterogeneous_job_id = _scope_id(scope[2], zero_is_missing=True) if len(scope) > 2 else None
        heterogeneous_job_offset = _scope_id(scope[3]) if len(scope) > 3 else None
        if array_job_id is None:
            array_task_id = None
        if heterogeneous_job_id is None:
            heterogeneous_job_offset = None
        requested = _LOG_JOB_ID.fullmatch(requested_job_id)
        if requested is not None and requested.group("task") is not None:
            array_job_id = array_job_id or requested.group("job")
            array_task_id = array_task_id or requested.group("task")
        return JobLogMetadata(
            job_id=requested_job_id,
            user=user,
            state=normalize_job_state(state),
            state_raw=state,
            job_name=name,
            working_directory=_optional(workdir),
            stdout_path=_optional(stdout),
            stderr_path=_optional(stderr),
            array_job_id=array_job_id,
            array_task_id=array_task_id,
            heterogeneous_job_id=heterogeneous_job_id,
            heterogeneous_job_offset=heterogeneous_job_offset,
            patterns_expanded=True,
        )
    return None


def resolve_log_paths(metadata: JobLogMetadata) -> dict[str, str]:
    """Return normalized, distinct paths keyed by their UI source."""

    stdout = _resolve_path(metadata.stdout_path, metadata)
    stderr = _resolve_path(metadata.stderr_path, metadata)
    if stdout is None and stderr is None:
        return {}
    if stdout is not None and stdout == stderr:
        return {"combined": stdout}
    paths: dict[str, str] = {}
    if stdout is not None:
        paths["stdout"] = stdout
    if stderr is not None:
        paths["stderr"] = stderr
    return paths


def _metadata_from_mapping(
    record: dict[str, Any],
    requested_job_id: str,
) -> JobLogMetadata | None:
    job_id = _text(_find(record, "job_id", "jobid", "job_id_raw", "jobidraw"))
    if job_id is None:
        return None
    if job_id != requested_job_id:
        return None
    requested = _LOG_JOB_ID.fullmatch(requested_job_id)
    derived_array_job = requested.group("job") if requested and requested.group("task") else None
    derived_array_task = requested.group("task") if requested else None
    state_raw = _state_text(_find(record, "job_state", "jobstate", "state")) or "UNKNOWN"
    array_job_id = _scope_id(
        _find(record, "array_job_id", "arrayjobid"),
        zero_is_missing=True,
    )
    array_task_id = _scope_id(_find(record, "array_task_id", "arraytaskid", "array_task_string"))
    heterogeneous_job_id = _scope_id(
        _find(record, "heterogeneous_job_id", "het_job_id", "hetjobid"),
        zero_is_missing=True,
    )
    heterogeneous_job_offset = _scope_id(
        _find(
            record,
            "heterogeneous_job_offset",
            "het_job_offset",
            "hetjoboffset",
        )
    )
    if array_job_id is None:
        array_task_id = None
    if heterogeneous_job_id is None:
        heterogeneous_job_offset = None
    return JobLogMetadata(
        job_id=requested_job_id,
        user=_slurm_user(_text(_find(record, "user_name", "username", "user_id", "user"))),
        state=normalize_job_state(state_raw),
        state_raw=state_raw,
        job_name=_text(_find(record, "name", "job_name", "jobname")) or requested_job_id,
        working_directory=_optional(
            _text(
                _find(
                    record,
                    "current_working_directory",
                    "working_directory",
                    "work_dir",
                    "workdir",
                )
            )
        ),
        stdout_path=_optional(
            _text(_find(record, "standard_output", "stdout", "std_out", "stdout_expanded"))
        ),
        stderr_path=_optional(
            _text(_find(record, "standard_error", "stderr", "std_err", "stderr_expanded"))
        ),
        array_job_id=array_job_id or derived_array_job,
        array_task_id=array_task_id or derived_array_task,
        heterogeneous_job_id=heterogeneous_job_id,
        heterogeneous_job_offset=heterogeneous_job_offset,
    )


def _scontrol_fields(line: str) -> dict[str, str]:
    matches = list(_SCONTROL_FIELD.finditer(line))
    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        values[match.group("key")] = line[start:end].strip()
    return values


def _find(mapping: dict[str, Any], *aliases: str) -> object | None:
    normalized = {_normalize_key(key): value for key, value in mapping.items()}
    for alias in aliases:
        value = normalized.get(_normalize_key(alias))
        if value is not None:
            return cast(object, value)
    for value in mapping.values():
        if isinstance(value, dict):
            nested = _find(value, *aliases)
            if nested is not None:
                return nested
    return None


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _state_text(value: object | None) -> str | None:
    if isinstance(value, dict):
        current = value.get("current")
        if isinstance(current, list) and current:
            return _text(current[0])
        return _text(value.get("name") or value.get("value"))
    if isinstance(value, list) and value:
        return _text(value[0])
    return _text(value)


def _text(value: object | None) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dict):
        for key in ("name", "string", "value", "number", "id"):
            if key in value:
                text = _text(value[key])
                if text is not None:
                    return text
    return None


def _optional(value: str | None) -> str | None:
    if value is None or value.strip().lower() in _NO_VALUE:
        return None
    return value.strip()


def _scope_id(value: object | None, *, zero_is_missing: bool = False) -> str | None:
    """Normalize Slurm's optional ID wrappers without inventing scope ID zero."""

    if isinstance(value, dict) and value.get("set") is False:
        return None
    result = _optional(_text(value))
    if zero_is_missing and result == "0":
        return None
    return result


def _slurm_user(value: str | None) -> str:
    if value is None:
        return ""
    return value.split("(", maxsplit=1)[0].strip()


def _resolve_path(value: str | None, metadata: JobLogMetadata) -> str | None:
    path = _optional(value)
    if path is None or path == "/dev/null":
        return None
    if "\x00" in path or len(path.encode("utf-8")) > _MAX_PATH_BYTES:
        raise JobLogMetadataParseError("Slurm returned an invalid output path")

    replacements = {
        "%": "%",
        "j": metadata.job_id,
        "A": metadata.array_job_id or metadata.job_id.split("_", maxsplit=1)[0],
        "a": metadata.array_task_id or "",
        "u": metadata.user,
        "x": metadata.job_name,
    }

    def replace_pattern(match: re.Match[str]) -> str:
        token = match.group("token")
        replacement = replacements[token]
        if token == "a" and not replacement:
            raise JobLogMetadataParseError("an array output pattern is ambiguous")
        width = match.group("width")
        if width and replacement.isdigit():
            replacement = replacement.zfill(int(width))
        return replacement

    if not metadata.patterns_expanded:
        path = _PATTERN.sub(replace_pattern, path)
        if "%" in path:
            raise JobLogMetadataParseError("Slurm returned an unsupported output pattern")
    if not path.startswith("/"):
        workdir = metadata.working_directory
        if workdir is None or not workdir.startswith("/"):
            raise JobLogMetadataParseError("a relative output path has no absolute work directory")
        path = str(PurePosixPath(workdir) / path)
    return posixpath.normpath(path)
