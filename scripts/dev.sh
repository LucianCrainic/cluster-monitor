#!/usr/bin/env bash

set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_pid=""
frontend_pid=""

if [[ -f "$repository_root/.env" ]]; then
  set -a
  # .env is a local, user-controlled shell environment file.
  source "$repository_root/.env"
  set +a
fi

stop_services() {
  trap - EXIT INT TERM

  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi
  if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
  fi

  [[ -z "$backend_pid" ]] || wait "$backend_pid" 2>/dev/null || true
  [[ -z "$frontend_pid" ]] || wait "$frontend_pid" 2>/dev/null || true
}

trap stop_services EXIT INT TERM

"$repository_root/scripts/backend.sh" &
backend_pid=$!
"$repository_root/scripts/frontend.sh" &
frontend_pid=$!

echo "Backend starting on http://127.0.0.1:8000"
echo "Frontend starting on http://127.0.0.1:5173"
echo "Press Ctrl-C to stop both services."

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done

exit_status=0
if ! kill -0 "$backend_pid" 2>/dev/null; then
  wait "$backend_pid" || exit_status=$?
else
  wait "$frontend_pid" || exit_status=$?
fi

exit "$exit_status"
