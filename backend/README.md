# cluster-monitor backend

The local FastAPI service for `cluster-monitor`. It provides normalized Slurm
monitoring plus opt-in job submission and cancellation.
It also exposes a read-only Server-Sent Events endpoint for live Slurm job
stdout and stderr.
It provides an enriched topology snapshot and explicitly opt-in, read-only
remote directory listing and UTF-8 text preview endpoints.

```bash
uv sync --extra dev
uv run uvicorn cluster_monitor.main:app --host 127.0.0.1 --port 8000 --reload
```

Set `CLUSTER_MONITOR_CONFIG` to override the cluster YAML path. Without it, the
service checks `config/clusters.yaml`, then `config/clusters.example.yaml`, and
finally uses its packaged mock-only configuration.

The asynchronous OpenSSH backend supports JSON capability detection with
fixed-field read fallbacks. Write actions are disabled by default and require
`allow_job_actions: true` for the selected cluster plus the
`X-Cluster-Monitor-Action: confirmed` request header. Batch scripts are
validated and passed to `sbatch` over standard input; cancellation is limited
to one positive numeric base job ID and rejects array or heterogeneous scope.
Inherited `SBATCH_*` controls are removed immediately before submission, while
the ordinary login environment is retained.

Mutation timeouts and dropped SSH connections are reported as uncertain
outcomes and are never retried automatically. SSH output capture is bounded to
8 MiB per stream and overflow content is discarded. Tests use mock data and
fake executors; they do not require or modify a real Slurm cluster.

`GET /api/clusters/{cluster_id}/jobs/{job_id}/logs/stream` accepts only an
allocation or explicit numeric array-task ID. The SSH backend checks the job
owner against `id -un`, obtains output paths from `scontrol` and expanded
`sacct` metadata, and passes each normalized path as one quoted `tail` argument.
It never accepts a path from the client. Pending jobs wait for Slurm to create
their files, terminal jobs return a 200-line snapshot, and live jobs use
`tail --follow=name --retry` until completion or browser disconnect. Log data
and resolved paths are not written to application logs.

`GET /api/clusters/{cluster_id}/topology` combines rich `scontrol --json`
partition/node data with live `sinfo` allocation counts and the optional output
of `scontrol show topology`. Empty or unsupported physical topology falls back
to a flat partition/resource map.

The two `POST /api/clusters/{cluster_id}/files/*` routes require
`allow_file_browsing: true`. Paths appear only in JSON bodies and are passed as
one SSH argument to a static isolated helper. The helper has no write operation,
caps listings at 500 entries, and previews only valid UTF-8 ordinary files up
to 1 MiB. Responses are marked `Cache-Control: no-store`.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
```

From the repository root, `make generate-api` exports OpenAPI and regenerates
the frontend component types with the standard-library generator in
`backend/scripts/generate_typescript.py`.
