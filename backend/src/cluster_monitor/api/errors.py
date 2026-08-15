"""Stable JSON translation for application and framework errors."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from cluster_monitor.api.schemas import ApiError, ApiErrorResponse
from cluster_monitor.exceptions import ClusterMonitorError
from cluster_monitor.logging import get_logger

logger = get_logger("api.errors")


def _response(
    status_code: int,
    *,
    code: str,
    message: str,
    cluster_id: str | None = None,
    details: Any | None = None,
) -> JSONResponse:
    payload = ApiErrorResponse(
        error=ApiError(
            code=code,
            message=message,
            cluster_id=cluster_id,
            details=details,
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(exclude_none=True))


async def cluster_monitor_exception_handler(
    request: Request,
    exc: ClusterMonitorError,
) -> JSONResponse:
    del request
    log = logger.warning if exc.status_code >= 500 else logger.info
    log(
        "api_error code=%s status=%d cluster_id=%s",
        exc.code,
        exc.status_code,
        exc.cluster_id or "-",
    )
    return _response(
        exc.status_code,
        code=exc.code,
        message=exc.message,
        cluster_id=exc.cluster_id,
        details=exc.details,
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    del request
    details = [
        {
            "location": [str(part) for part in error["loc"]],
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return _response(
        422,
        code="validation_error",
        message="The request parameters are invalid.",
        details=details,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    del request
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    details = None if isinstance(exc.detail, str) else exc.detail
    return _response(
        exc.status_code,
        code="http_error",
        message=message,
        details=details,
    )


async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unexpected_api_error method=%s path=%s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return _response(
        500,
        code="internal_error",
        message="An unexpected error occurred.",
    )
