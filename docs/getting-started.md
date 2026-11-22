# Getting started

Build and install a standalone executable from the repository root:

```sh
make install-bin
```

The default installation directory is `~/.local/bin`. If it is outside your
`PATH`, call `~/.local/bin/cluster-monitor` or set `BINDIR` when installing.

Run `cluster-monitor --demo` to try the monitor offline. Switch among the
four views with `1` through `4`, or click a tab. Move between rows with the
arrow keys and press `Enter` to see the full record. Use `/` to search by
text or `f` to choose a job, partition, or node state.

Run `cluster-monitor --init-config` to create your user configuration. Follow
the [configuration guide](configuration.md) to connect a cluster.
