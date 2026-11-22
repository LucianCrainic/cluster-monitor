# Development

Use Rust 1.88 or newer with Cargo, rustfmt, and Clippy. Run these commands
from the repository root.

| Command | Purpose |
| --- | --- |
| `make demo` | Open the monitor with bundled data |
| `make test` | Test config, Slurm parsing, and terminal behavior |
| `make lint` | Run rustfmt and Clippy |
| `make typecheck` | Run Cargo checks |
| `make build` | Build the release executable in `target/release` |
| `make install-bin` | Install the executable to `BINDIR` |

Demo mode and automated tests run locally. Build and run on each target OS
and architecture where you plan to distribute a binary.
