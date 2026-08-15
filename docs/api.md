# API

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
| `GET /api/clusters/{cluster_id}/topology` | Enriched partitions, nodes, and optional Slurm physical topology |
| `POST /api/clusters/{cluster_id}/files/list` | List one SSH-visible directory read-only |
| `POST /api/clusters/{cluster_id}/files/preview` | Preview one bounded UTF-8 regular file read-only |
| `GET /api/clusters/{cluster_id}/jobs` | Running and pending jobs |
| `GET /api/clusters/{cluster_id}/jobs/{job_id}` | One job's details |
| `GET /api/clusters/{cluster_id}/jobs/{job_id}/logs/stream` | Path-free SSE stream of job stdout/stderr |
| `GET /api/clusters/{cluster_id}/history` | Recently completed jobs |
| `POST /api/clusters/{cluster_id}/jobs` | Submit a validated batch script |
| `DELETE /api/clusters/{cluster_id}/jobs/{job_id}` | Request cancellation of one active base job |

Where supported, the jobs and history endpoints accept filters such as `state`,
`partition`, `user`, and `limit`. Both mutation endpoints require
`X-Cluster-Monitor-Action: confirmed`, and remain unavailable unless
`allow_job_actions: true` is set for that cluster. The API does not accept shell
commands or arbitrary remote arguments. Consult `/docs` for the exact schema
implemented by the checked-out revision.

Remote file paths are carried in JSON request bodies rather than URLs. Both
file responses use `Cache-Control: no-store`; there are no create, update,
rename, upload, or delete filesystem routes.