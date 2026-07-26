"""Small HTTP-only response schemas."""

from __future__ import annotations

from typing import Any, Literal

from cluster_monitor.models.base import ApiModel


class HealthResponse(ApiModel):
    status: Literal["ok"] = "ok"
    service: Literal["cluster-monitor"] = "cluster-monitor"
    version: str


class ApiError(ApiModel):
    code: str
    message: str
    cluster_id: str | None = None
    details: Any | None = None


class ApiErrorResponse(ApiModel):
    error: ApiError
