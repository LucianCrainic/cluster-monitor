#!/usr/bin/env bash

set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
frontend_dir="$repository_root/frontend"

if [[ -f "$repository_root/.env" ]]; then
  set -a
  # .env is a local, user-controlled shell environment file.
  source "$repository_root/.env"
  set +a
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "error: npm is required; install a current Node.js LTS release" >&2
  exit 127
fi

if [[ ! -f "$frontend_dir/package.json" ]]; then
  echo "error: frontend/package.json was not found" >&2
  exit 1
fi

cd "$frontend_dir"
exec npm run dev
