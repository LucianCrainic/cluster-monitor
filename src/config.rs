use std::{
    collections::HashSet,
    env, fs,
    io::{ErrorKind, Write},
    path::{Path, PathBuf},
    time::Duration,
};

use anyhow::{Context, Result, bail, ensure};
use serde::Deserialize;

const DEMO: &str = include_str!("../config/clusters.yaml");

#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Backend {
    Mock,
    Ssh,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Cluster {
    pub id: String,
    pub name: String,
    pub backend: Backend,
    pub ssh_host: Option<String>,
    #[serde(default = "current_user")]
    pub slurm_user: String,
    #[serde(default = "command_timeout")]
    pub command_timeout_seconds: f64,
}

#[derive(Debug, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Refresh {
    pub partitions_seconds: u64,
    pub jobs_seconds: u64,
    pub history_seconds: u64,
    pub nodes_seconds: u64,
}

impl Default for Refresh {
    fn default() -> Self {
        Self {
            partitions_seconds: 30,
            jobs_seconds: 10,
            history_seconds: 60,
            nodes_seconds: 30,
        }
    }
}

#[derive(Debug, Deserialize, Default)]
#[serde(default, deny_unknown_fields)]
pub struct Application {
    pub refresh: Refresh,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    #[serde(default)]
    pub application: Application,
    pub clusters: Vec<Cluster>,
}

pub fn user_path() -> Result<PathBuf> {
    let xdg = env::var_os("XDG_CONFIG_HOME").map(PathBuf::from);
    let base = match xdg.filter(|path| path.is_absolute()) {
        Some(path) => path,
        None => PathBuf::from(env::var_os("HOME").context("HOME is unset")?).join(".config"),
    };
    Ok(base.join("cluster-monitor/config.yaml"))
}

pub fn init() -> Result<PathBuf> {
    let path = user_path()?;
    let parent = path.parent().context("Invalid config directory")?;
    fs::create_dir_all(parent).with_context(|| format!("Could not create {}", parent.display()))?;
    let mut file =
        tempfile::NamedTempFile::new_in(parent).context("Could not stage configuration")?;
    file.write_all(DEMO.as_bytes())
        .context("Could not write configuration")?;
    file.persist_noclobber(&path).map_err(|error| {
        if error.error.kind() == ErrorKind::AlreadyExists {
            anyhow::anyhow!("Configuration already exists at {}", path.display())
        } else {
            anyhow::anyhow!("Could not create configuration at {}", path.display())
        }
    })?;
    Ok(path)
}

pub fn load(path: Option<&Path>, demo: bool) -> Result<Config> {
    if demo {
        return parse(DEMO, "bundled demo");
    }
    let selected = match path {
        Some(path) => path.to_path_buf(),
        None => user_path()?,
    };
    match fs::read_to_string(&selected) {
        Ok(text) => parse(&text, &selected.display().to_string()),
        Err(error)
            if error.kind() == ErrorKind::NotFound && path.is_none() && !selected.is_symlink() =>
        {
            parse(DEMO, "bundled demo")
        }
        Err(error) => Err(error).with_context(|| format!("Could not read {}", selected.display())),
    }
}

fn parse(text: &str, source: &str) -> Result<Config> {
    // Accept settings files from the former interface without enabling retired features.
    let mut value: serde_yaml_ng::Value =
        serde_yaml_ng::from_str(text).map_err(|_| anyhow::anyhow!("Invalid YAML in {source}"))?;
    if let Some(app) = value
        .get_mut("application")
        .and_then(|v| v.as_mapping_mut())
    {
        app.remove("bind_host");
        app.remove("port");
        if let Some(refresh) = app.get_mut("refresh").and_then(|v| v.as_mapping_mut()) {
            refresh.remove("overview_seconds");
        }
    }
    if let Some(clusters) = value.get_mut("clusters").and_then(|v| v.as_sequence_mut()) {
        for cluster in clusters.iter_mut().filter_map(|v| v.as_mapping_mut()) {
            cluster.remove("allow_job_actions");
            cluster.remove("allow_file_browsing");
        }
    }
    let config: Config = serde_yaml_ng::from_value(value)
        .map_err(|_| anyhow::anyhow!("Invalid configuration fields in {source}"))?;
    validate(&config)?;
    Ok(config)
}

fn validate(config: &Config) -> Result<()> {
    ensure!(
        !config.clusters.is_empty(),
        "Configure at least one cluster"
    );
    let intervals = &config.application.refresh;
    for seconds in [
        intervals.partitions_seconds,
        intervals.jobs_seconds,
        intervals.history_seconds,
        intervals.nodes_seconds,
    ] {
        ensure!(
            (1..=3600).contains(&seconds),
            "Refresh intervals must be between 1 and 3600 seconds"
        );
    }

    let mut ids = HashSet::new();
    for (index, cluster) in config.clusters.iter().enumerate() {
        let id = cluster.id.as_bytes();
        let position = index + 1;
        let safe_id = |c: &u8| c.is_ascii_lowercase() || c.is_ascii_digit();
        ensure!(
            id.len() <= 64
                && id.first().is_some_and(safe_id)
                && id.last().is_some_and(safe_id)
                && id.iter().all(|c| safe_id(c) || *c == b'-'),
            "Invalid ID for cluster {position}"
        );
        ensure!(ids.insert(&cluster.id), "Cluster IDs must be unique");
        ensure!(
            !cluster.name.trim().is_empty()
                && cluster.name.chars().count() <= 100
                && !cluster.name.chars().any(char::is_control),
            "Invalid name for cluster {position}"
        );
        if let Some(host) = &cluster.ssh_host {
            ensure!(valid_host(host), "Invalid SSH alias for cluster {position}");
        } else if cluster.backend == Backend::Ssh {
            bail!("Missing ssh_host for cluster {position}");
        }
        ensure!(
            valid_user(&cluster.slurm_user),
            "Invalid Slurm user for cluster {position}"
        );
        ensure!(
            cluster.command_timeout_seconds.is_finite()
                && cluster.command_timeout_seconds > 0.0
                && cluster.command_timeout_seconds <= 300.0,
            "Invalid command timeout for cluster {position}"
        );
    }
    Ok(())
}

impl Cluster {
    pub fn timeout(&self) -> Duration {
        Duration::from_secs_f64(self.command_timeout_seconds)
    }
}

fn valid_host(host: &str) -> bool {
    host.len() <= 255
        && host
            .as_bytes()
            .first()
            .is_some_and(u8::is_ascii_alphanumeric)
        && host
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_.-".contains(&c))
}

pub fn valid_user(user: &str) -> bool {
    user.len() <= 128
        && user
            .as_bytes()
            .first()
            .is_some_and(|c| c.is_ascii_alphabetic() || *c == b'_')
        && user
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_.-".contains(&c))
}

fn command_timeout() -> f64 {
    15.0
}
fn current_user() -> String {
    "current".into()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn demo_and_legacy_settings_load() {
        let demo = parse(DEMO, "demo").unwrap();
        assert_eq!(demo.clusters[0].backend, Backend::Mock);
        let legacy = DEMO
            .replace(
                "  refresh:",
                "  port: 8000\n  refresh:\n    overview_seconds: 10",
            )
            .replace(
                "    backend: mock",
                "    backend: mock\n    allow_file_browsing: true",
            );
        assert!(parse(&legacy, "legacy").is_ok());
    }

    #[test]
    fn rejects_unsafe_hosts_and_unknown_fields() {
        let unsafe_config = DEMO.replace("backend: mock", "backend: ssh\n    ssh_host: -F");
        assert!(
            parse(&unsafe_config, "test")
                .unwrap_err()
                .to_string()
                .contains("SSH alias")
        );
        let secret = DEMO.replace("backend: mock", "backend: mock\n    password: test-secret");
        let err = parse(&secret, "test").unwrap_err();
        assert!(!err.to_string().contains("test-secret"));
    }
}
