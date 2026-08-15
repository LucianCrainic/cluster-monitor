# Configuration

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
    allow_file_browsing: true
```

Configuration is validated during backend startup. Cluster IDs must be unique,
and an SSH backend requires `ssh_host`. `allow_job_actions` defaults to `false`;
set it to `true` only for a cluster on which this local user should be able to
submit and cancel jobs. For SSH clusters, that opt-in is accepted only with
`slurm_user: current`, so actions cannot target a configured identity override.
`allow_file_browsing` also defaults to `false`; enabling it exposes only
directory listing and bounded text preview operations through the remote SSH
identity. It is independent of job actions and adds no filesystem mutation API.

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
  allow_file_browsing: false
```

`ssh_host` is an OpenSSH alias, not a hostname accepted from the browser.
`slurm_user: current` means the remote login user. Keep the mock cluster in the
same file while bringing up a real entry so the UI remains usable when the VPN
or cluster is unavailable. After read-only monitoring works, review the
security notes and change `allow_job_actions` to `true` to expose the Submit
page and cancellation controls for that cluster.

## OpenSSH alias

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

## Password-only clusters with ControlMaster

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

## Live-cluster quick start

Once the alias and ignored YAML entry are in place:

```bash
ssh -MNf sapienza-hpc
ssh -O check sapienza-hpc
CLUSTER_MONITOR_CONFIG=config/clusters.local.yaml make dev
```

Open <http://127.0.0.1:5173>, select the real cluster in **Active cluster**, and
start with Overview. An empty Jobs page is valid when the selected user has no
running or pending work. The History API uses a bounded seven-day `sacct`
lookback.

To try live logs, submit a batch job that writes periodically and open its
**Job Details → Logs** tab. The viewer requests the latest 200 lines from each
distinct stdout/stderr file and follows new output until Slurm reports a final
state. It also works for completed jobs and explicit array-task IDs such as
`12345_7`. The remote login user must own the job; `allow_job_actions` is not
required because viewing logs is read-only. For example:

```bash
ssh sapienza-hpc 'mkdir -p "$HOME/cluster-monitor-logs"'
ssh sapienza-hpc sbatch <<'EOF'
#!/usr/bin/env bash
#SBATCH --job-name=log-smoke
#SBATCH --output=cluster-monitor-logs/%j.out
#SBATCH --error=cluster-monitor-logs/%j.err
for n in 1 2 3 4 5; do
  echo "stdout $n"
  echo "stderr $n" >&2
  sleep 2
done
EOF
```

Closing the Logs tab, changing jobs, or leaving the page aborts the HTTP stream
and tears down its SSH `tail` processes. When finished, stop the app with
Ctrl-C and optionally close the reusable SSH connection:

```bash
ssh -O exit sapienza-hpc
```