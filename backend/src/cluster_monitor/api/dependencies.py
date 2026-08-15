"""FastAPI dependencies."""

from fastapi import Request

from cluster_monitor.exceptions import ConfigurationError
from cluster_monitor.services import ClusterService


def get_cluster_service(request: Request) -> ClusterService:
    service = getattr(request.app.state, "cluster_service", None)
    if not isinstance(service, ClusterService):
        raise ConfigurationError("The cluster service did not initialize.")
    return service
