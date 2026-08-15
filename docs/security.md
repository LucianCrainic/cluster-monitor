# Security model

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
- Log streaming accepts only allocation IDs and explicit numeric array-task
  IDs. It resolves output paths from `scontrol`/`sacct`, expands Slurm filename
  patterns server-side, and never accepts a browser-provided path. The job
  owner must match `id -un`; stdout/stderr pointing at one file are tailed only
  once. Job content and resolved paths are excluded from application logs and
  SSE metadata.
- Every live SSH stream has a bounded diagnostic capture and queue. Browser
  disconnect or generator cancellation terminates, then drains or kills, the
  local SSH child; the remote session consequently cannot retain an orphaned
  foreground `tail` owned by the viewer.
- Remote browsing is an explicit per-cluster opt-in. A static isolated Python
  helper receives the selected absolute path as one SSH argument, lists at most
  500 entries, and previews only valid UTF-8 ordinary files up to 1 MiB. It
  never writes, and devices, sockets, FIFOs, oversized files, and binary content
  receive metadata-only responses. Paths and contents are excluded from logs.
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