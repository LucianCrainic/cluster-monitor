# Troubleshooting

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
- **File browsing or preview is unavailable:** confirm the selected cluster has
  `allow_file_browsing: true`, restart the backend after changing YAML, and
  verify the sidebar indicates file browsing is enabled.
- **Slurm rejects an action:** inspect the non-sensitive API message, then check
  the cluster's partition, account, QoS, resource, ownership, and state rules.
- **An action outcome is uncertain:** do not immediately repeat it. Refresh Jobs
  and, if necessary, verify with `squeue` or `sacct` before taking another
  action.
- **Commands are missing:** rerun `make install` and verify `uv`, Node.js, and npm
  are available on `PATH`.