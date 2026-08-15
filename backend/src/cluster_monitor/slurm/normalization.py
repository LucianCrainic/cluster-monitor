"""Normalization of transport-specific Slurm state strings."""

from __future__ import annotations

import re

from cluster_monitor.models import JobState, NodeState

_JOB_STATE_SUFFIX = re.compile(r"[*+~$@#!%^]+$")
_NODE_STATE_SUFFIXES = frozenset("*~#!%$@^-")

_FAILED_JOB_STATES = {
    "BOOT_FAIL",
    "DEADLINE",
    "FAILED",
    "NODE_FAIL",
    "PREEMPTED",
    "REVOKED",
    "SPECIAL_EXIT",
}


def normalize_job_state(raw_state: str | None) -> JobState:
    """Map Slurm states and decorated values to stable frontend categories."""

    if not raw_state:
        return JobState.UNKNOWN

    cleaned = _JOB_STATE_SUFFIX.sub("", raw_state.strip().upper())
    base = cleaned.split(maxsplit=1)[0].split("+", maxsplit=1)[0]
    mapping = {
        "PENDING": JobState.PENDING,
        "CONFIGURING": JobState.PENDING,
        "RUNNING": JobState.RUNNING,
        "COMPLETING": JobState.RUNNING,
        "COMPLETED": JobState.COMPLETED,
        "CANCELLED": JobState.CANCELLED,
        "TIMEOUT": JobState.TIMEOUT,
        "OUT_OF_MEMORY": JobState.OUT_OF_MEMORY,
        "SUSPENDED": JobState.SUSPENDED,
        "STOPPED": JobState.SUSPENDED,
        "RESIZING": JobState.RUNNING,
    }
    if base in _FAILED_JOB_STATES:
        return JobState.FAILED
    return mapping.get(base, JobState.UNKNOWN)


def normalize_node_state(raw_state: str | None) -> NodeState:
    """Map Slurm node states, flags, and composites to stable categories."""

    if not raw_state:
        return NodeState.UNKNOWN

    cleaned, suffixes = _split_node_suffixes(raw_state.strip().upper())
    components = {part for part in re.split(r"[+\s]+", cleaned) if part}

    # Sinfo suffixes are flags layered on every base state. Apply them first so
    # an unresponsive, powered-down, or maintenance node is never counted as
    # usable capacity merely because its base state is IDLE, MIXED, or ALLOCATED.
    if suffixes & set("*~#!%@^"):
        return NodeState.DOWN
    if "$" in suffixes:
        return NodeState.DRAINED
    if "-" in suffixes:
        return NodeState.UNKNOWN

    if components & {"DRAIN", "DRAINED", "DRAINING", "DRNG", "FAILING", "FAILG", "FAIL"}:
        return NodeState.DRAINED
    if components & {"MAINT", "MAINTENANCE"}:
        return NodeState.DRAINED
    if components & {
        "DOWN",
        "ERROR",
        "INVAL",
        "INVALID",
        "NO_RESPOND",
        "POWERED_DOWN",
        "POWERING_DOWN",
        "POWER_DOWN",
        "UNKNOWN",
    }:
        return NodeState.DOWN
    if "COMPLETING" in components:
        return NodeState.COMPLETING
    if components & {"MIXED", "MIX"}:
        return NodeState.MIXED
    if components & {"ALLOCATED", "ALLOC"}:
        return NodeState.ALLOCATED
    if "IDLE" in components:
        if components & {
            "BLOCKED",
            "CLOUD",
            "FUTURE",
            "NPC",
            "PERFCTRS",
            "PLANNED",
            "POWERING_UP",
            "REBOOT_ISSUED",
            "REBOOT_REQUESTED",
            "RESERVED",
        }:
            return NodeState.UNKNOWN
        return NodeState.IDLE
    return NodeState.UNKNOWN


def _split_node_suffixes(value: str) -> tuple[str, frozenset[str]]:
    suffixes: set[str] = set()
    end = len(value)
    while end and value[end - 1] in _NODE_STATE_SUFFIXES:
        suffixes.add(value[end - 1])
        end -= 1
    return value[:end], frozenset(suffixes)
