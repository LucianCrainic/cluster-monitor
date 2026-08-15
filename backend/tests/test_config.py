from __future__ import annotations

import traceback
from pathlib import Path

import pytest

from cluster_monitor.config import CONFIG_ENV_VAR, load_config
from cluster_monitor.exceptions import ConfigurationError
from cluster_monitor.models import BackendType


def _write_config(path: Path, clusters: str) -> Path:
    path.write_text(
        f"application:\n  refresh:\n    overview_seconds: 5\nclusters:\n{clusters}",
        encoding="utf-8",
    )
    return path


def test_loads_valid_yaml_and_applies_defaults(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path / "clusters.yaml",
        "  - id: local-mock\n"
        "    name: Mock\n"
        "    backend: mock\n"
        "  - id: research\n"
        "    name: Research Cluster\n"
        "    backend: ssh\n"
        "    ssh_host: research-hpc\n",
    )

    config = load_config(path)

    assert config.clusters[0].backend is BackendType.MOCK
    assert config.clusters[1].ssh_host == "research-hpc"
    assert config.clusters[1].command_timeout_seconds == 15
    assert config.clusters[1].allow_job_actions is False
    assert config.clusters[1].allow_file_browsing is False
    assert config.application.refresh.overview_seconds == 5
    assert config.application.refresh.history_seconds == 60
    assert config.application.bind_host == "127.0.0.1"


def test_environment_path_overrides_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_config(
        tmp_path / "from-env.yaml",
        "  - id: environment\n    name: Environment Mock\n    backend: mock\n",
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, str(path))

    assert load_config().clusters[0].id == "environment"


def test_ssh_job_actions_require_current_remote_user(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path / "job-actions.yaml",
        "  - id: actions-current\n"
        "    name: Actions as login user\n"
        "    backend: ssh\n"
        "    ssh_host: actions-hpc\n"
        "    slurm_user: current\n"
        "    allow_job_actions: true\n"
        "  - id: monitor-other\n"
        "    name: Read-only monitoring override\n"
        "    backend: ssh\n"
        "    ssh_host: monitor-hpc\n"
        "    slurm_user: another-user\n"
        "    allow_job_actions: false\n",
    )

    config = load_config(path)

    assert config.clusters[0].allow_job_actions is True
    assert config.clusters[0].slurm_user == "current"
    assert config.clusters[1].allow_job_actions is False
    assert config.clusters[1].slurm_user == "another-user"


@pytest.mark.parametrize(
    ("clusters", "message"),
    [
        (
            "  - id: repeated\n"
            "    name: First\n"
            "    backend: mock\n"
            "  - id: repeated\n"
            "    name: Second\n"
            "    backend: mock\n",
            "duplicate cluster id",
        ),
        (
            "  - id: missing-host\n    name: SSH\n    backend: ssh\n",
            "ssh_host is required",
        ),
        (
            "  - id: Bad_ID\n    name: Invalid ID\n    backend: mock\n",
            "cluster id must contain",
        ),
        (
            "  - id: unsafe-host\n"
            "    name: Unsafe Host\n"
            "    backend: ssh\n"
            "    ssh_host: hpc;echo-bad\n",
            "valid OpenSSH host alias",
        ),
        (
            "  - id: unsafe-action-user\n"
            "    name: Unsafe action identity\n"
            "    backend: ssh\n"
            "    ssh_host: actions-hpc\n"
            "    slurm_user: another-user\n"
            "    allow_job_actions: true\n",
            "allow_job_actions requires slurm_user to be 'current'",
        ),
    ],
)
def test_rejects_invalid_cluster_configuration(
    tmp_path: Path,
    clusters: str,
    message: str,
) -> None:
    path = _write_config(tmp_path / "invalid.yaml", clusters)

    with pytest.raises(ConfigurationError, match=message):
        load_config(path)


def test_rejects_non_loopback_bind_address(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.yaml"
    path.write_text(
        "application:\n"
        "  bind_host: 0.0.0.0\n"
        "clusters:\n"
        "  - id: local-mock\n"
        "    name: Mock\n"
        "    backend: mock\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="loopback"):
        load_config(path)


def test_missing_explicit_config_has_clear_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"

    with pytest.raises(ConfigurationError, match="does not exist"):
        load_config(missing)


def test_validation_traceback_does_not_expose_rejected_secret(tmp_path: Path) -> None:
    secret = "SUPERSECRET-DO-NOT-LOG"
    path = tmp_path / "contains-secret.yaml"
    path.write_text(
        "clusters:\n"
        "  - id: local-mock\n"
        "    name: Mock\n"
        "    backend: mock\n"
        f"    password: {secret}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as caught:
        load_config(path)

    rendered_traceback = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert secret not in rendered_traceback
    assert caught.value.__cause__ is None


def test_yaml_error_traceback_does_not_expose_source_line(tmp_path: Path) -> None:
    secret = "ANOTHER-SUPERSECRET"
    path = tmp_path / "invalid-secret.yaml"
    path.write_text(f"clusters:\n  - password: [{secret}\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as caught:
        load_config(path)

    rendered_traceback = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert secret not in rendered_traceback
    assert caught.value.__cause__ is None
