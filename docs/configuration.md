# Configuration

The monitor reads `~/.config/cluster-monitor/config.yaml` by default.
An absolute `XDG_CONFIG_HOME` changes the base directory. Run
`cluster-monitor --config-path` to print the exact path.

```sh
cluster-monitor --init-config
```

This creates a starter YAML file if the destination is empty. You can also copy
your existing cluster YAML to that path, or give its path explicitly with
`cluster-monitor --config PATH`. The monitor opens the bundled demo when no
user configuration exists. `--demo` overrides the user configuration.

## SSH clusters

Set `id` and `name` for display and selection, `backend: ssh`, and
`ssh_host` to the alias configured in OpenSSH. Keep `slurm_user: current` to
monitor jobs for the remote login account, or set another account if the
scheduler allows you to inspect it. Use `--cluster ID` to select a starting
cluster. See [example YAML](../config/clusters.example.yaml).

`command_timeout_seconds` defaults to 15. Establish any VPN, gateway, or
multiplexed session your cluster requires before launching the monitor.

## Refresh intervals

Set these values in seconds under `application.refresh`.

| Setting | View | Default |
| --- | --- | --- |
| `partitions_seconds` | Overview | 30 |
| `jobs_seconds` | Queue | 10 |
| `history_seconds` | History | 60 |
| `nodes_seconds` | Nodes | 30 |
