"""FastAPI application factory."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException

from cluster_monitor import __version__
from cluster_monitor.api import router
from cluster_monitor.api.errors import (
    cluster_monitor_exception_handler,
    http_exception_handler,
    unexpected_exception_handler,
    validation_exception_handler,
)
from cluster_monitor.config import MonitorConfig, load_config
from cluster_monitor.exceptions import ClusterMonitorError
from cluster_monitor.logging import get_logger
from cluster_monitor.services import ClusterService
from cluster_monitor.slurm import BackendRegistry

logger = get_logger("http")


def _build_service(
    config: MonitorConfig,
    registry: BackendRegistry | None = None,
) -> ClusterService:
    return ClusterService(config, registry or BackendRegistry(config))


def create_app(
    config: MonitorConfig | None = None,
    *,
    config_path: str | Path | None = None,
    registry: BackendRegistry | None = None,
) -> FastAPI:
    """Create an app with optional in-memory dependencies for tests."""

    initial_service = _build_service(config, registry) if config is not None else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if initial_service is not None:
            app.state.cluster_service = initial_service
        else:
            loaded_config = load_config(config_path)
            app.state.cluster_service = _build_service(loaded_config)
        yield

    application = FastAPI(
        title="cluster-monitor API",
        summary="Local Slurm monitoring API with guarded job actions",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Accept", "Content-Type", "X-Cluster-Monitor-Action"],
    )
    application.include_router(router)
    application.add_exception_handler(
        ClusterMonitorError,
        cluster_monitor_exception_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(
        HTTPException,
        http_exception_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(
        Exception,
        unexpected_exception_handler,
    )

    @application.middleware("http")
    async def log_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1_000
        logger.info(
            "api_request method=%s path=%s status=%d duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    return application


app = create_app()
