"""Domain exceptions that are translated into stable API errors."""

from __future__ import annotations

from typing import Any


class ClusterMonitorError(Exception):
    """Base class for expected application failures."""

    code = "cluster_monitor_error"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        cluster_id: str | None = None,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.cluster_id = cluster_id
        self.details = details


class ConfigurationError(ClusterMonitorError):
    """The YAML configuration could not be loaded or validated."""

    code = "configuration_error"
    status_code = 500


class ClusterNotFoundError(ClusterMonitorError):
    """A requested cluster ID is not configured."""

    code = "cluster_not_found"
    status_code = 404

    def __init__(self, cluster_id: str) -> None:
        super().__init__(f"Cluster '{cluster_id}' is not configured.", cluster_id=cluster_id)


class ClusterUnavailableError(ClusterMonitorError):
    """A configured cluster cannot currently provide monitoring data."""

    code = "cluster_unavailable"
    status_code = 503

    def __init__(self, cluster_id: str, message: str) -> None:
        super().__init__(message, cluster_id=cluster_id)


class JobNotFoundError(ClusterMonitorError):
    """A job does not exist in the selected cluster."""

    code = "job_not_found"
    status_code = 404

    def __init__(self, cluster_id: str, job_id: str) -> None:
        super().__init__(
            f"Job '{job_id}' was not found in cluster '{cluster_id}'.",
            cluster_id=cluster_id,
            details={"job_id": job_id},
        )


class JobActionForbiddenError(ClusterMonitorError):
    """A mutation was requested for a job owned by another user."""

    code = "job_action_forbidden"
    status_code = 403

    def __init__(self, cluster_id: str, job_id: str) -> None:
        super().__init__(
            "Only jobs owned by the configured Slurm user can be changed.",
            cluster_id=cluster_id,
            details={"job_id": job_id},
        )


class JobActionScopeUnsupportedError(ClusterMonitorError):
    """A mutation could affect more than one Slurm job component."""

    code = "job_action_scope_unsupported"
    status_code = 409

    def __init__(self, cluster_id: str, job_id: str, scope: str) -> None:
        super().__init__(
            "Cluster Monitor cannot cancel job arrays or heterogeneous jobs. "
            "Use Slurm directly when the cancellation scope can be reviewed explicitly.",
            cluster_id=cluster_id,
            details={"job_id": job_id, "scope": scope},
        )


class JobActionsDisabledError(ClusterMonitorError):
    """A cluster has not explicitly opted into state-changing actions."""

    code = "job_actions_disabled"
    status_code = 403

    def __init__(self, cluster_id: str) -> None:
        super().__init__(
            "Job submission and cancellation are disabled for this cluster.",
            cluster_id=cluster_id,
        )


class JobActionRejectedError(ClusterMonitorError):
    """Slurm rejected a requested submission or cancellation."""

    code = "job_action_rejected"
    status_code = 409

    def __init__(self, cluster_id: str, action: str, *, job_id: str | None = None) -> None:
        message = (
            "Slurm rejected the job submission. Check the requested resources and cluster policy."
            if action == "submit"
            else "Slurm could not cancel the job. It may already have finished or changed state."
        )
        super().__init__(
            message,
            cluster_id=cluster_id,
            details={"action": action, **({"job_id": job_id} if job_id else {})},
        )


class JobActionUncertainError(ClusterMonitorError):
    """A timeout made the outcome of a mutation impossible to determine."""

    code = "job_action_outcome_uncertain"
    status_code = 504

    def __init__(self, cluster_id: str, action: str, *, job_id: str | None = None) -> None:
        message = (
            "The submission response timed out, so the job may still have been created. "
            "Refresh Jobs before trying again."
            if action == "submit"
            else "The cancellation response timed out, so the job may already be cancelled. "
            "Refresh the job before trying again."
        )
        super().__init__(
            message,
            cluster_id=cluster_id,
            details={"action": action, **({"job_id": job_id} if job_id else {})},
        )
