#!/usr/bin/env bash

set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_dir="$repository_root/backend"

if [[ -f "$repository_root/.env" ]]; then
  set -a
  # .env is a local, user-controlled shell environment file.
  source "$repository_root/.env"
  set +a
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is required; install it from https://docs.astral.sh/uv/" >&2
  exit 127
fi

if [[ ! -f "$backend_dir/pyproject.toml" ]]; then
  echo "error: backend/pyproject.toml was not found" >&2
  exit 1
fi

config_path="${CLUSTER_MONITOR_CONFIG:-config/clusters.yaml}"
if [[ "$config_path" != /* ]]; then
  config_path="$repository_root/$config_path"
fi

export CLUSTER_MONITOR_CONFIG="$config_path"

cd "$backend_dir"
exec uv run uvicorn cluster_monitor.main:app \
  --reload \
  --host 127.0.0.1 \
  --port 8000
