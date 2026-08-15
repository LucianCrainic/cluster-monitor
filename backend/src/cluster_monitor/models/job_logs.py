"""Typed events emitted while viewing Slurm job output."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from cluster_monitor.models.base import ApiModel
from cluster_monitor.models.job import JobState

JobLogSource = Literal["stdout", "stderr", "combined"]


class JobLogMetadataEvent(ApiModel):
    type: Literal["metadata"] = "metadata"
    job_id: str
    state: JobState
    sources: list[JobLogSource]
    initial_lines: int


class JobLogStatusEvent(ApiModel):
    type: Literal["status"] = "status"
    status: Literal["waiting", "live", "finalizing"]
    message: str


class JobLogChunkEvent(ApiModel):
    type: Literal["chunk"] = "chunk"
    source: JobLogSource
    sequence: int = Field(ge=1)
    text: str


class JobLogErrorEvent(ApiModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool


class JobLogCompleteEvent(ApiModel):
    type: Literal["complete"] = "complete"
    reason: Literal["snapshot_complete", "job_finished", "unavailable"]


JobLogEvent = Annotated[
    JobLogMetadataEvent
    | JobLogStatusEvent
    | JobLogChunkEvent
    | JobLogErrorEvent
    | JobLogCompleteEvent,
    Field(discriminator="type"),
]


@dataclass(frozen=True, slots=True)
class JobLogSession:
    """A preflighted, single-consumer job-log event stream."""

    events: AsyncIterator[JobLogEvent]
