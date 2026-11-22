# Architecture

Ratatui draws directly into the terminal through Crossterm. The Rust process
owns the terminal, the configured cluster connections, and the current view.

```text
Ratatui + Crossterm
        │
        ▼
App state and Tokio refresh tasks
    ├── Demo snapshots
    └── Local OpenSSH ── Slurm commands
            └── JSON or fixed-field text parser
```

Network operations run as cancellable Tokio tasks. On a cluster change the app
clears the old views and discards responses from the previous cluster.
Refreshing a view preserves the selected row when the record is still present.

The Slurm reader uses `sinfo`, `scontrol show`, `squeue`, and `sacct`.
It prefers JSON and falls back to fixed fields. The Rust source is in `src/`
and parser compatibility fixtures are in `tests/fixtures/`.
