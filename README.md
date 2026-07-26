# cluster-monitor

`cluster-monitor` is a local web application for inspecting Slurm clusters and,
when explicitly enabled for a cluster, submitting and cancelling jobs through
the OpenSSH client already configured on your computer. It is intended for
university and research clusters that are reachable after joining a VPN.

The app works end to end with deterministic mock data, so development does not
require a VPN, SSH server, or Slurm installation. Its real OpenSSH backend has
been exercised against Slurm 24.11.1 using `sinfo`, `squeue`, and `sacct`.
Submission uses `sbatch` and cancellation uses `scancel`; those write paths are
disabled per cluster by default. Other scheduler versions retain explicit
fixed-field read fallbacks but may need additional compatibility fixtures.

## Architecture

```text
React + TanStack Query (127.0.0.1:5173)
                |
                | /api through the Vite development proxy
                v
FastAPI service (127.0.0.1:8000)
                |
                v
        SlurmBackend interface
          /             \
MockSlurmBackend           SshSlurmBackend
                          |
                          v
              local OpenSSH -> remote Slurm
```

The frontend consumes one normalized API regardless of backend type. FastAPI
routes depend on a backend abstraction instead of invoking SSH or Slurm
directly. The SSH implementation detects Slurm JSON support once per cluster,
normalizes scheduler responses in isolated parsers, falls back to documented
fixed-field output, and briefly caches successful snapshots. This leaves room
for a future `slurmrestd` backend without changing the API or frontend.

The repository is a monorepo:

- `backend/` contains the Python 3.12 FastAPI application, typed models,
  cluster backends, and pytest tests.
- `frontend/` contains the React, TypeScript, Vite, and TanStack Query client.
- `config/` contains the tracked mock configuration and a real-cluster example.
- `scripts/` contains the local backend, frontend, and combined launchers.

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

## Configuration

Cluster definitions and refresh intervals live in YAML. The default file is
`config/clusters.yaml`; `CLUSTER_MONITOR_CONFIG` overrides that path. Relative
paths passed to the root scripts are resolved from the repository root.

```yaml
application:
  refresh:
    overview_seconds: 10
    jobs_seconds: 10
    nodes_seconds: 30
    partitions_seconds: 30
    history_seconds: 60

clusters:
  - id: local-mock
    name: Local Mock Cluster
    backend: mock
    allow_job_actions: true
```

Configuration is validated during backend startup. Cluster IDs must be unique,
and an SSH backend requires `ssh_host`. `allow_job_actions` defaults to `false`;
set it to `true` only for a cluster on which this local user should be able to
submit and cancel jobs. For SSH clusters, that opt-in is accepted only with
`slurm_user: current`, so actions cannot target a configured identity override.

For a personal real-cluster experiment, use the ignored local filename so that
site details are not accidentally committed:

```bash
cp config/clusters.example.yaml config/clusters.local.yaml
export CLUSTER_MONITOR_CONFIG=config/clusters.local.yaml
make dev
```

Before starting the app, verify the exact non-interactive SSH mode it uses:

```bash
ssh -T \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=yes \
  sapienza-hpc \
  'sinfo --version'
```

If this fails while an interactive `ssh sapienza-hpc` succeeds, establish a
ControlMaster connection as shown below or fix the non-interactive remote
`PATH`. The app does not open a password prompt.

An SSH entry has this shape:

```yaml
- id: sapienza
  name: Sapienza HPC Cluster
  backend: ssh
  ssh_host: sapienza-hpc
  slurm_user: current
  command_timeout_seconds: 15
  allow_job_actions: false
```

`ssh_host` is an OpenSSH alias, not a hostname accepted from the browser.
`slurm_user: current` means the remote login user. Keep the mock cluster in the
same file while bringing up a real entry so the UI remains usable when the VPN
or cluster is unavailable. After read-only monitoring works, review the
security notes below and change `allow_job_actions` to `true` to expose the
Submit page and cancellation controls for that cluster.

### OpenSSH alias

Put cluster-specific hostnames and usernames in `~/.ssh/config`, not in the
application:

```sshconfig
Host sapienza-hpc
    HostName frontend.example.university.it
    User university_username
    ServerAliveInterval 30
    ServerAliveCountMax 3
    ControlMaster auto
    ControlPath ~/.ssh/control-%C
    ControlPersist 15m
```

`frontend.example.university.it` and `university_username` are placeholders.
Replace them with values from the cluster administrator. Connect once from a
terminal:

```bash
ssh sapienza-hpc
```

For a previously unknown host, compare the displayed host-key fingerprint with
an authoritative value supplied by the institution before accepting it. The
application must not disable host-key checking or automatically trust a key.

### Password-only clusters with ControlMaster

The web application never asks for, stores, forwards, or automates an SSH
password. For a password-only cluster, the `ControlMaster` settings above let
OpenSSH reuse a connection authenticated in your terminal:

```bash
# Join the VPN first. This prompts in the terminal, then backgrounds the master.
ssh -MNf sapienza-hpc

# Confirm that the reusable connection exists.
ssh -O check sapienza-hpc

# Start the application while the master remains available.
make dev

# Close the master when finished.
ssh -O exit sapienza-hpc
```

The `~/.ssh` directory must exist and have suitable permissions. With
`ControlPersist 15m`, OpenSSH may keep the socket alive for up to 15 minutes
after the last client disconnects. Key authentication and an SSH agent are also
supported through ordinary OpenSSH configuration.

### Live-cluster quick start

Once the alias and ignored YAML entry are in place:

```bash
ssh -MNf sapienza-hpc
ssh -O check sapienza-hpc
CLUSTER_MONITOR_CONFIG=config/clusters.local.yaml make dev
```

Open <http://127.0.0.1:5173>, select the real cluster in **Active cluster**, and
start with Overview. An empty Jobs page is valid when the selected user has no
running or pending work. The History API uses a bounded seven-day `sacct`
lookback. When finished, stop the app with Ctrl-C and optionally close the
reusable SSH connection:

```bash
ssh -O exit sapienza-hpc
```

## API

All application routes are under `/api`:

| Method and path | Purpose |
| --- | --- |
| `GET /api/health` | Local service health |
| `GET /api/settings` | Frontend-safe refresh settings and default cluster |
| `GET /api/clusters` | Configured clusters |
| `GET /api/clusters/{cluster_id}` | Connection and cluster details |
| `GET /api/clusters/{cluster_id}/overview` | Node and job summary |
| `GET /api/clusters/{cluster_id}/partitions` | Partition status |
| `GET /api/clusters/{cluster_id}/nodes` | Node resources and state |
| `GET /api/clusters/{cluster_id}/jobs` | Running and pending jobs |
| `GET /api/clusters/{cluster_id}/jobs/{job_id}` | One job's details |
| `GET /api/clusters/{cluster_id}/history` | Recently completed jobs |
| `POST /api/clusters/{cluster_id}/jobs` | Submit a validated batch script |
| `DELETE /api/clusters/{cluster_id}/jobs/{job_id}` | Request cancellation of one active base job |

Where supported, the jobs and history endpoints accept filters such as `state`,
`partition`, `user`, and `limit`. Both mutation endpoints require
`X-Cluster-Monitor-Action: confirmed`, and remain unavailable unless
`allow_job_actions: true` is set for that cluster. The API does not accept shell
commands or arbitrary remote arguments. Consult `/docs` for the exact schema
implemented by the checked-out revision.

## Developer commands

| Command | Action |
| --- | --- |
| `make install` | Install backend and frontend dependencies |
| `make backend` | Start FastAPI with reload |
| `make frontend` | Start Vite |
| `make dev` | Start and supervise both development servers |
| `make generate-api` | Refresh OpenAPI and generated frontend types |
| `make test` | Run pytest and frontend tests |
| `make lint` | Run Ruff checks/format validation and ESLint |
| `make typecheck` | Run mypy and TypeScript checking |
| `make build` | Produce the frontend production bundle |

The tests are hermetic: they use mock data and fixtures rather than a real SSH
server or Slurm cluster.

Optional pre-commit hooks reuse the installed project tools:

```bash
uv tool install pre-commit
pre-commit install
pre-commit run --all-files
```

## Security model

- This is a single-user local tool. Backend and frontend default to loopback.
- Cluster credentials never belong in YAML, `.env`, frontend state, browser
  storage, URLs, or logs.
- Authentication is delegated to OpenSSH, its agent, and its multiplexed
  control connections.
- Host-key verification remains enabled. Verify new fingerprints out of band.
- Remote commands must be built from fixed executables and validated argument
  arrays without `shell=True` or raw frontend interpolation.
- Job actions are disabled per cluster by default. Enabling them requires local
  YAML configuration, and each API call also requires an explicit confirmation
  header. The frontend presents a separate review or confirmation step.
- Submitted scripts are validated, rejected if they contain `#SBATCH`
  directives, and sent to `sbatch` over standard input rather than appearing in
  process arguments or application logs. Resource options are built from
  bounded typed fields. Immediately before `sbatch`, a static wrapper removes
  inherited `SBATCH_*` variables and `SLURM_CLUSTERS` so they cannot add or
  redirect scheduler options, while preserving ordinary login and module
  environment variables for the submitted job.
- Cancellation accepts one positive numeric base job ID, checks the actual SSH
  login user and current active state, and rejects array or heterogeneous scope
  metadata before invoking `scancel --quiet` for only that ID. Slurm remains
  the final authorization authority.
- SSH stdout and stderr are captured concurrently with an 8 MiB limit per
  stream. Overflow is discarded without entering logs or API responses; an
  overflow after a mutation is dispatched is reported as an uncertain outcome.
- Mutations are never automatically retried. If SSH closes or times out after a
  request is sent, the API reports an uncertain outcome so the user can inspect
  the queue before deciding what to do next.
- CORS is intended only for the local Vite development origin.

The launch scripts deliberately fix both services to loopback; binding to
`0.0.0.0` is not a supported public deployment model. This application has no
multi-user authentication layer.

## Known limitations

- Live compatibility has been verified on one Slurm 24.11.1 cluster. JSON
  schema changes in other Slurm/data-parser versions may require another
  sanitized fixture and parser alias.
- Real job details currently come from `sacct`; active jobs that are not yet
  visible to accounting receive normalized queue fields but may lack paths and
  accounting values. A targeted `scontrol` detail path is still planned.
- Browser disconnects are not yet propagated into a live SSH request scope;
  executor task cancellation itself is implemented and tested.
- The frontend currently implements Overview, Jobs, and Job Details. Nodes,
  Partitions, and Job History already have mock API endpoints but not pages.
- Write support is deliberately limited to submission and cancellation.
  Requeue, hold, release, dependency editing, and job-array or heterogeneous-job
  cancellation are not supported. Cancellation is asynchronous: a successful
  response means Slurm accepted the request, not that the job has stopped.
- Submission limits are conservative application caps, not values discovered
  from each partition. The scheduler can still reject an otherwise valid
  request because of site policy, account, QoS, or resource availability.
- The app keeps no long-term metrics database.
- Production serving of the built frontend is not yet the primary workflow;
  local development uses Vite and FastAPI as separate processes.
- VPN availability, SSH authorization, scheduler policy, and remote command
  availability are outside the application's control.

## Roadmap

1. Propagate API client disconnects into SSH task cancellation and add
   integration coverage for that request lifecycle.
2. Add Nodes, Partitions, and History pages, then add targeted `scontrol`
   job-detail parsing.
3. Add sanitized compatibility fixtures for additional Slurm releases and pin
   versioned JSON data-parser schemas where available.
4. Add an optional `slurmrestd` backend without changing the frontend API.
5. Discover partition-specific submission constraints and add explicitly scoped
   array, requeue, hold, and release actions only with matching safeguards.
6. Add durable action correlation and reconciliation for uncertain submissions,
   then consider read-only historical metrics.

## Troubleshooting

- **The UI cannot reach the API:** confirm both processes are running and ports
  5173 and 8000 are free. Use `make backend` and `make frontend` separately to
  isolate startup output.
- **Configuration fails at startup:** check YAML indentation, unique IDs, the
  backend value (`mock` or `ssh`), and `ssh_host` on SSH entries.
- **`ssh sapienza-hpc` fails:** solve VPN, DNS, host-key, and authentication
  issues in a terminal first. The browser cannot repair SSH configuration.
- **A password prompt is not visible:** establish the ControlMaster connection
  in a terminal before starting the app; the backend is non-interactive.
- **The cluster is unavailable in the selector:** run `ssh -O check
  sapienza-hpc`, then run the non-interactive `sinfo --version` probe above.
- **Overview works but one data page fails:** run `sinfo --version` and note the
  Slurm version. The installed data-parser schema may need a sanitized
  compatibility fixture; API errors deliberately do not expose scheduler
  output.
- **Submit or Cancel is unavailable:** confirm the selected cluster has
  `allow_job_actions: true` and `slurm_user: current`, restart the backend after
  changing YAML, and verify the sidebar says **Job actions enabled**.
- **Slurm rejects an action:** inspect the non-sensitive API message, then check
  the cluster's partition, account, QoS, resource, ownership, and state rules.
- **An action outcome is uncertain:** do not immediately repeat it. Refresh Jobs
  and, if necessary, verify with `squeue` or `sacct` before taking another
  action.
- **Commands are missing:** rerun `make install` and verify `uv`, Node.js, and npm
  are available on `PATH`.
