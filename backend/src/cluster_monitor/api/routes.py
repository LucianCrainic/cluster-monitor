"""Monitoring and guarded job-action HTTP routes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from cluster_monitor import __version__
from cluster_monitor.api.dependencies import get_cluster_service
from cluster_monitor.api.schemas import ApiErrorResponse, HealthResponse
from cluster_monitor.models import (
    ClientSettings,
    Cluster,
    ClusterOverview,
    ClusterTopology,
    Job,
    JobCancellationReceipt,
    JobDetails,
    JobLogEvent,
    JobState,
    JobSubmissionReceipt,
    JobSubmissionRequest,
    Node,
    NodeState,
    Partition,
    RemoteDirectory,
    RemoteDirectoryRequest,
    RemoteFilePreview,
    RemoteFilePreviewRequest,
)
from cluster_monitor.services import ClusterService

router = APIRouter(prefix="/api")
Service = Annotated[ClusterService, Depends(get_cluster_service)]
ClusterId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$",
    ),
]
JobId = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.+\-]+$"),
]
CancelableJobId = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=r"^[1-9][0-9]*$"),
]
LoggableJobId = Annotated[
    str,
    Path(min_length=1, max_length=128, pattern=r"^[1-9][0-9]*(?:_[0-9]+)?$"),
]
ActionConfirmation = Annotated[
    Literal["confirmed"],
    Header(alias="X-Cluster-Monitor-Action"),
]

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"model": ApiErrorResponse},
    404: {"model": ApiErrorResponse},
    409: {"model": ApiErrorResponse},
    422: {"model": ApiErrorResponse},
    503: {"model": ApiErrorResponse},
    504: {"model": ApiErrorResponse},
}


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(version=__version__)


@router.get("/settings", response_model=ClientSettings)
async def settings(service: Service) -> ClientSettings:
    return service.get_client_settings()


@router.get("/clusters", response_model=list[Cluster], responses=ERROR_RESPONSES)
async def list_clusters(service: Service) -> list[Cluster]:
    return await service.list_clusters()


@router.get(
    "/clusters/{cluster_id}",
    response_model=Cluster,
    responses=ERROR_RESPONSES,
)
async def get_cluster(cluster_id: ClusterId, service: Service) -> Cluster:
    return await service.get_cluster(cluster_id)


@router.get(
    "/clusters/{cluster_id}/overview",
    response_model=ClusterOverview,
    responses=ERROR_RESPONSES,
)
async def get_overview(cluster_id: ClusterId, service: Service) -> ClusterOverview:
    return await service.get_overview(cluster_id)


@router.get(
    "/clusters/{cluster_id}/partitions",
    response_model=list[Partition],
    responses=ERROR_RESPONSES,
)
async def get_partitions(cluster_id: ClusterId, service: Service) -> list[Partition]:
    return await service.get_partitions(cluster_id)


@router.get(
    "/clusters/{cluster_id}/nodes",
    response_model=list[Node],
    responses=ERROR_RESPONSES,
)
async def get_nodes(
    cluster_id: ClusterId,
    service: Service,
    state: Annotated[NodeState | None, Query()] = None,
    partition: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> list[Node]:
    return await service.get_nodes(cluster_id, state=state, partition=partition)


@router.get(
    "/clusters/{cluster_id}/topology",
    response_model=ClusterTopology,
    responses=ERROR_RESPONSES,
)
async def get_topology(cluster_id: ClusterId, service: Service) -> ClusterTopology:
    return await service.get_topology(cluster_id)


@router.post(
    "/clusters/{cluster_id}/files/list",
    response_model=RemoteDirectory,
    responses=ERROR_RESPONSES,
)
async def list_remote_directory(
    cluster_id: ClusterId,
    request: RemoteDirectoryRequest,
    service: Service,
    response: Response,
) -> RemoteDirectory:
    response.headers["Cache-Control"] = "no-store"
    return await service.list_remote_directory(cluster_id, request)


@router.post(
    "/clusters/{cluster_id}/files/preview",
    response_model=RemoteFilePreview,
    responses=ERROR_RESPONSES,
)
async def preview_remote_file(
    cluster_id: ClusterId,
    request: RemoteFilePreviewRequest,
    service: Service,
    response: Response,
) -> RemoteFilePreview:
    response.headers["Cache-Control"] = "no-store"
    return await service.preview_remote_file(cluster_id, request)


@router.get(
    "/clusters/{cluster_id}/jobs",
    response_model=list[Job],
    responses=ERROR_RESPONSES,
)
async def get_jobs(
    cluster_id: ClusterId,
    service: Service,
    state: Annotated[JobState | None, Query()] = None,
    partition: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    user: Annotated[
        str | None,
        Query(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Job]:
    return await service.get_jobs(
        cluster_id,
        user=user,
        state=state,
        partition=partition,
        limit=limit,
    )


@router.post(
    "/clusters/{cluster_id}/jobs",
    response_model=JobSubmissionReceipt,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
async def submit_job(
    cluster_id: ClusterId,
    request: JobSubmissionRequest,
    service: Service,
    confirmation: ActionConfirmation,
) -> JobSubmissionReceipt:
    del confirmation
    return await service.submit_job(cluster_id, request)


@router.get(
    "/clusters/{cluster_id}/jobs/{job_id}",
    response_model=JobDetails,
    responses=ERROR_RESPONSES,
)
async def get_job(cluster_id: ClusterId, job_id: JobId, service: Service) -> JobDetails:
    return await service.get_job(cluster_id, job_id)


@router.get(
    "/clusters/{cluster_id}/jobs/{job_id}/logs/stream",
    response_class=StreamingResponse,
    responses={
        **ERROR_RESPONSES,
        200: {
            "description": "Path-free Server-Sent Events carrying job output.",
            "content": {"text/event-stream": {}},
        },
    },
)
async def stream_job_logs(
    request: Request,
    cluster_id: ClusterId,
    job_id: LoggableJobId,
    service: Service,
) -> StreamingResponse:
    session = await service.open_job_log_stream(cluster_id, job_id)

    async def events() -> AsyncIterator[str]:
        iterator = session.events.__aiter__()
        pending: asyncio.Task[JobLogEvent] | None = None

        async def next_event() -> JobLogEvent:
            return await iterator.__anext__()

        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(next_event())
                done, _ = await asyncio.wait({pending}, timeout=15.0)
                if not done:
                    if await request.is_disconnected():
                        return
                    yield ": heartbeat\n\n"
                    continue
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    return
                finally:
                    pending = None
                yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            close = getattr(iterator, "aclose", None)
            if callable(close):
                close_task = asyncio.create_task(close())
                try:
                    await asyncio.shield(close_task)
                except asyncio.CancelledError:
                    await close_task
                    raise

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete(
    "/clusters/{cluster_id}/jobs/{job_id}",
    response_model=JobCancellationReceipt,
    responses=ERROR_RESPONSES,
)
async def cancel_job(
    cluster_id: ClusterId,
    job_id: CancelableJobId,
    service: Service,
    confirmation: ActionConfirmation,
) -> JobCancellationReceipt:
    del confirmation
    return await service.cancel_job(cluster_id, job_id)


@router.get(
    "/clusters/{cluster_id}/history",
    response_model=list[Job],
    responses=ERROR_RESPONSES,
)
async def get_history(
    cluster_id: ClusterId,
    service: Service,
    state: Annotated[JobState | None, Query()] = None,
    partition: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    user: Annotated[
        str | None,
        Query(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[Job]:
    return await service.get_recent_jobs(
        cluster_id,
        user=user,
        state=state,
        partition=partition,
        limit=limit,
    )
