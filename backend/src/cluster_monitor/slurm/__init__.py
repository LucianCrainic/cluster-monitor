"""Slurm backend interfaces and implementations."""

from cluster_monitor.slurm.backend import SlurmBackend
from cluster_monitor.slurm.capabilities import (
    SlurmCapabilities,
    SlurmVersionDetectionError,
    detect_slurm_capabilities,
    parse_slurm_version,
)
from cluster_monitor.slurm.commands import (
    SlurmCommand,
    build_sacct_json_probe,
    build_sinfo_json_probe,
    build_squeue_json_probe,
    build_version_command,
)
from cluster_monitor.slurm.mock import MockSlurmBackend
from cluster_monitor.slurm.normalization import normalize_job_state, normalize_node_state
from cluster_monitor.slurm.registry import BackendRegistry
from cluster_monitor.slurm.ssh_backend import SshSlurmBackend
from cluster_monitor.slurm.unavailable import UnavailableSshSlurmBackend

__all__ = [
    "BackendRegistry",
    "MockSlurmBackend",
    "SlurmBackend",
    "SlurmCapabilities",
    "SlurmCommand",
    "SlurmVersionDetectionError",
    "SshSlurmBackend",
    "UnavailableSshSlurmBackend",
    "build_sacct_json_probe",
    "build_sinfo_json_probe",
    "build_squeue_json_probe",
    "build_version_command",
    "detect_slurm_capabilities",
    "normalize_job_state",
    "normalize_node_state",
    "parse_slurm_version",
]
