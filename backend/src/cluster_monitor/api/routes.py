"""Monitoring and guarded job-action HTTP routes."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, status

from cluster_monitor import __version__
from cluster_monitor.api.dependencies import get_cluster_service
from cluster_monitor.api.schemas import ApiErrorResponse, HealthResponse
from cluster_monitor.models import (
    ClientSettings,
    Cluster,
    ClusterOverview,
    Job,
    JobCancellationReceipt,
    JobDetails,
    JobState,
    JobSubmissionReceipt,
    JobSubmissionRequest,
    Node,
    NodeState,
    Partition,
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
