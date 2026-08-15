# Architecture

## Overview

`cluster-monitor` is a local web application for inspecting Slurm clusters and,
when explicitly enabled for a cluster, submitting and cancelling jobs through
the OpenSSH client already configured on your computer. It is intended for
university and research clusters that are reachable after joining a VPN.

The app works end to end with deterministic mock data, so development does not
require a VPN, SSH server, or Slurm installation. Its real OpenSSH backend has
been exercised against Slurm 24.11.1 using `sinfo`, `squeue`, and `sacct`.
Submission uses `sbatch`, cancellation uses `scancel`, and job details can
stream scheduler-resolved stdout/stderr files with `tail`; write paths are
disabled per cluster by default. Other scheduler versions retain explicit
fixed-field read fallbacks but may need additional compatibility fixtures.

## Component diagram

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

## Repository layout

The repository is a monorepo:

- `backend/` contains the Python 3.12 FastAPI application, typed models,
  cluster backends, and pytest tests.
- `frontend/` contains the React, TypeScript, Vite, and TanStack Query client.
- `config/` contains the tracked mock configuration and a real-cluster example.
- `scripts/` contains the local backend, frontend, and combined launchers.
- `docs/` contains this documentation, linked from the repository README.