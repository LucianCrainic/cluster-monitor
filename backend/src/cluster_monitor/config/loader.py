"""YAML configuration discovery and loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from cluster_monitor.config.models import MonitorConfig
from cluster_monitor.exceptions import ConfigurationError

CONFIG_ENV_VAR = "CLUSTER_MONITOR_CONFIG"


class RuntimeSettings(BaseSettings):
    """Small environment layer used only to locate the YAML configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    config_path: Path | None = Field(default=None, validation_alias=CONFIG_ENV_VAR)


def _default_candidates() -> tuple[Path, ...]:
    repository_root = Path(__file__).resolve().parents[4]
    return (
        Path.cwd() / "config" / "clusters.yaml",
        Path.cwd() / "config" / "clusters.example.yaml",
        repository_root / "config" / "clusters.yaml",
        repository_root / "config" / "clusters.example.yaml",
        Path(__file__).with_name("default_clusters.yaml"),
    )


def resolve_config_path(path: str | Path | None = None) -> Path:
    """Resolve an explicit path, environment override, or safe default."""

    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            raise ConfigurationError(f"Configuration file does not exist: {candidate}")
        return candidate.resolve()

    environment_path = RuntimeSettings().config_path
    if environment_path is not None:
        candidate = environment_path.expanduser()
        if not candidate.is_file():
            raise ConfigurationError(f"{CONFIG_ENV_VAR} points to a missing file: {candidate}")
        return candidate.resolve()

    seen: set[Path] = set()
    for candidate in _default_candidates():
        candidate = candidate.resolve()
        if candidate not in seen and candidate.is_file():
            return candidate
        seen.add(candidate)

    raise ConfigurationError(
        "No cluster configuration found. Set CLUSTER_MONITOR_CONFIG to a YAML file."
    )


def load_config(path: str | Path | None = None) -> MonitorConfig:
    """Load and validate a cluster configuration from YAML."""

    config_path = resolve_config_path(path)
    try:
        raw: Any = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"Could not read configuration: {config_path}") from exc
    except yaml.YAMLError:
        # Parser exceptions can include source snippets. Never chain potentially
        # secret configuration content into startup logs.
        raise ConfigurationError(f"Invalid YAML in configuration: {config_path}") from None

    if not isinstance(raw, dict):
        raise ConfigurationError("Cluster configuration must be a YAML mapping.")

    try:
        return MonitorConfig.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False)
        )
        # Pydantic's original exception may contain rejected input values (for
        # example, a password field added by mistake). Expose only this summary.
        raise ConfigurationError(f"Invalid cluster configuration: {problems}") from None
