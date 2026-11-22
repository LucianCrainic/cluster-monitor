# SSH and cluster access

The monitor requests scheduler and account information through fixed commands
such as `squeue`, `sacct`, `sinfo`, `scontrol show`, and `id -un`. It runs
OpenSSH in batch mode with strict host key checking and uses your existing
OpenSSH authentication. Keep credentials in the authentication tools you
already use for SSH.

Cluster aliases and job filters are validated before execution. Remote
arguments are quoted before passing a command to OpenSSH. Captured command
output is bounded, and connection errors displayed in the terminal summarize
the failure without exposing remote command output.
