# Development

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

## Known limitations

- Live compatibility has been verified on one Slurm 24.11.1 cluster. JSON
  schema changes in other Slurm/data-parser versions may require another
  sanitized fixture and parser alias.
- Log viewing requires GNU-compatible `tail` on the submitter node. It supports
  base allocations and explicit numeric array tasks, but not job steps,
  heterogeneous components, or an ambiguous array leader.
- Manual reconnect deliberately starts a fresh 200-line snapshot; there is no
  durable byte cursor. The browser retains at most 5,000 lines and 2 MiB.
- Physical switch, block, or ring hierarchy is shown only when Slurm reports
  it. Flat clusters use the partition/resource map; rack placement is never
  inferred from hostnames.
- Partition compatibility is advisory and based on the captured Slurm snapshot.
  Slurm remains authoritative and chooses the actual nodes.
- File preview is limited to UTF-8 text/code up to 1 MiB. It does not render
  images, PDFs, tables, or binary formats, and intentionally cannot edit remote
  files.
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
2. Add time-series node and partition history without weakening the current
   live-snapshot model.
3. Add sanitized compatibility fixtures for additional Slurm releases and pin
   versioned JSON data-parser schemas where available.
4. Add an optional `slurmrestd` backend without changing the frontend API.
5. Discover partition-specific submission constraints and add explicitly scoped
   array, requeue, hold, and release actions only with matching safeguards.
6. Add durable action correlation and reconciliation for uncertain submissions,
   then consider read-only historical metrics.