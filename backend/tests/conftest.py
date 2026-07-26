from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from cluster_monitor.config import MonitorConfig
from cluster_monitor.main import create_app
from cluster_monitor.models import BackendType
from cluster_monitor.slurm import (
    BackendRegistry,
    MockSlurmBackend,
    UnavailableSshSlurmBackend,
)


@pytest.fixture
def monitor_config() -> MonitorConfig:
    return MonitorConfig.model_validate(
        {
            "application": {
                "refresh": {
                    "overview_seconds": 11,
                    "jobs_seconds": 12,
                    "nodes_seconds": 31,
                    "partitions_seconds": 32,
                    "history_seconds": 61,
                }
            },
            "clusters": [
                {
                    "id": "local-mock",
                    "name": "Local Mock Cluster",
                    "backend": "mock",
                    "allow_job_actions": True,
                },
                {
                    "id": "ssh-demo",
                    "name": "Unavailable SSH Cluster",
                    "backend": "ssh",
                    "ssh_host": "hpc-alias",
                },
            ],
        }
    )


@pytest.fixture
def client(monitor_config: MonitorConfig) -> Iterator[TestClient]:
    registry = BackendRegistry(
        monitor_config,
        factories={
            BackendType.MOCK: lambda config: MockSlurmBackend(config, delay_seconds=0),
            BackendType.SSH: UnavailableSshSlurmBackend,
        },
    )
    with TestClient(create_app(monitor_config, registry=registry)) as test_client:
        yield test_client
