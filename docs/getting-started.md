# Getting started

## Prerequisites

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/) for Python environments and dependencies
- Node.js 22.22 or newer with npm
- `make` and Bash for the convenience commands
- OpenSSH only when experimenting with a real cluster

Docker, a database, a local Slurm installation, and cluster access are not
required for mock mode.

## Quick start: mock mode

The tracked `config/clusters.yaml` contains only `local-mock` and is safe to use
immediately:

```bash
make install
make dev
```

Open <http://127.0.0.1:5173>. The backend API is available at
<http://127.0.0.1:8000>, and its interactive OpenAPI documentation is at
<http://127.0.0.1:8000/docs>.

The theme follows the operating-system preference until the light/dark toggle
is used, then stores only that theme choice in browser local storage. The mock
cluster enables job actions so submission and cancellation can be exercised
without touching a real scheduler.

The Jobs page shows the current scheduler queue. History shows up to 100 recent
accounting records for the selected cluster and configured user, refreshes on
the configured `history_seconds` interval, and links every record back to its
detail and Logs tabs. For the SSH backend, Slurm accounting covers the last
seven days.

`make dev` launches both processes and stops both when either process exits or
when you press Ctrl-C. To run them in separate terminals:

```bash
make backend
make frontend
```

The defaults bind both services to `127.0.0.1`; no service is intentionally
exposed to the local network.

## Setup in detail

Backend dependencies, including the development tools, are installed into
`backend/.venv`:

```bash
cd backend
uv sync --extra dev
uv run uvicorn cluster_monitor.main:app \
  --reload --host 127.0.0.1 --port 8000
```

When starting the backend directly from `backend/`, either rely on its default
repository config discovery or set an absolute configuration path:

```bash
export CLUSTER_MONITOR_CONFIG="$PWD/../config/clusters.yaml"
```

Frontend dependencies are installed from the npm lockfile:

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

Vite listens on `127.0.0.1:5173` and proxies relative `/api` requests to
`http://127.0.0.1:8000`. `VITE_API_BASE_URL` can override the API base for local
development, but it is normally best left unset.

The root launch scripts optionally load a local `.env`. Copy `.env.example`
only if you need a non-secret configuration-path or API-base override:

```bash
cp .env.example .env
```