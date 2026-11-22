# Troubleshooting

| Symptom | What to check |
| --- | --- |
| The monitor starts in demo mode | Use `cluster-monitor --config-path` to find the user YAML, or pass it with `--config`. |
| Cluster data is unavailable | Check your OpenSSH alias, connectivity, host key and any required SSH session. Press `r` to retry. |
| Job history is unavailable | Confirm the configured user can query accounting with `sacct`. |
| Data is stale | The most recent fetch failed. The status line shows the last successful update and the error. |
| Columns disappear in a compact terminal | Press `Enter` on a row for the full record. |
| A filtered view has no results | Press `Esc` from the records pane to clear the text and state filters. |
| Keystrokes appear in the search field | Press `Enter` to return to the records pane, or `Esc` to clear the search text. |
