mod demo;
mod parse;

use std::{process::Stdio, time::Duration};

use anyhow::{Context, Result, anyhow, ensure};
use tokio::{
    io::{AsyncRead, AsyncReadExt},
    process::Command,
    sync::OnceCell,
    time::timeout,
};

use self::parse::{
    HISTORY_FIELDS, NODES_FORMAT, PARTITIONS_FORMAT, QUEUE_FORMAT, jobs_json, jobs_text,
    nodes_json, nodes_text, partitions_json, partitions_text,
};
use crate::{
    config::{Backend, Cluster, valid_user},
    model::{Data, Job, Node, Partition, Snapshot, View},
};

const MAX_OUTPUT: u64 = 8 * 1024 * 1024;

pub struct Source {
    pub cluster: Cluster,
    version: OnceCell<String>,
    user: OnceCell<String>,
}

#[derive(Clone, Copy, Debug)]
enum Failure {
    Unreachable,
    Timeout,
    Command,
    Output,
}

impl Failure {
    fn fallback(self) -> bool {
        matches!(self, Self::Command | Self::Output)
    }

    fn error(self) -> anyhow::Error {
        let message = match self {
            Self::Unreachable => "OpenSSH could not connect. Check the network and SSH session.",
            Self::Timeout => "The SSH command timed out.",
            Self::Command => "A read-only Slurm command failed.",
            Self::Output => "Slurm returned more data than the monitor can read safely.",
        };
        anyhow!(message)
    }
}

impl Source {
    pub fn new(cluster: Cluster) -> Self {
        Self {
            cluster,
            version: OnceCell::new(),
            user: OnceCell::new(),
        }
    }

    pub async fn snapshot(&self, view: View) -> Result<Snapshot> {
        if self.cluster.backend == Backend::Mock {
            return Ok(demo::snapshot(view, &self.cluster.slurm_user));
        }

        let (version, data) = tokio::try_join!(self.version(), self.load(view))?;
        Ok(Snapshot {
            version: version.clone(),
            data,
        })
    }

    async fn version(&self) -> Result<&String> {
        self.version
            .get_or_try_init(|| async {
                let output = self
                    .execute("sinfo", &["--version"])
                    .await
                    .map_err(Failure::error)?;
                let version = output
                    .lines()
                    .find_map(|line| {
                        let candidate = line.trim().strip_prefix("slurm ")?.trim();
                        (candidate.len() <= 40
                            && candidate
                                .bytes()
                                .all(|b| b.is_ascii_alphanumeric() || b".-+_".contains(&b)))
                        .then(|| candidate.to_owned())
                    })
                    .context("Slurm did not report a version")?;
                Ok(version)
            })
            .await
    }

    async fn user(&self) -> Result<&str> {
        if self.cluster.slurm_user != "current" {
            return Ok(&self.cluster.slurm_user);
        }
        self.user
            .get_or_try_init(|| async {
                let output = self.execute("id", &["-un"]).await.map_err(Failure::error)?;
                let user = output.trim();
                ensure!(
                    valid_user(user),
                    "Could not determine the remote Slurm user"
                );
                Ok(user.to_owned())
            })
            .await
            .map(String::as_str)
    }

    async fn load(&self, view: View) -> Result<Data> {
        match view {
            View::Overview => {
                let (mut partitions, nodes) = tokio::try_join!(self.partitions(), self.nodes())?;
                for part in &mut partitions {
                    if part.hosts.is_empty() {
                        part.hosts = nodes
                            .iter()
                            .filter(|node| node.partitions.contains(&part.name))
                            .map(|node| node.name.as_str())
                            .collect::<Vec<_>>()
                            .join(", ");
                    }
                }
                Ok(Data::Overview { partitions, nodes })
            }
            View::Nodes => Ok(Data::Nodes(self.nodes().await?)),
            View::Queue | View::History => {
                let history = view == View::History;
                let mut jobs = self.jobs(history, None).await?;
                if history {
                    jobs.retain(Job::finished);
                    jobs.sort_by_key(|job| std::cmp::Reverse(job.recency()));
                    jobs.truncate(500);
                }
                Ok(Data::Jobs(jobs))
            }
        }
    }

    async fn partitions(&self) -> Result<Vec<Partition>> {
        let format = format!("--format={PARTITIONS_FORMAT}");
        let fallback = ["--noheader", "--summarize", &format];
        let details = self.execute("scontrol", &["--json", "show", "partition"]);
        let summary = self.json_or_text(
            ("sinfo", &["--json", "--summarize"]),
            partitions_json,
            ("sinfo", &fallback),
            partitions_text,
        );
        let (mut summary, details) = tokio::join!(summary, details);
        if let (Ok(parts), Ok(details)) = (&mut summary, details)
            && let Ok(details) = partitions_json(&details)
        {
            for part in parts {
                if let Some(info) = details.iter().find(|info| info.name == part.name) {
                    if part.limit.is_empty() {
                        part.limit.clone_from(&info.limit);
                    }
                    if part.state.is_empty() {
                        part.state.clone_from(&info.state);
                    }
                    if !info.hosts.is_empty() {
                        part.hosts.clone_from(&info.hosts);
                    }
                    if !info.qos.is_empty() {
                        part.qos.clone_from(&info.qos);
                    }
                    part.min_nodes = info.min_nodes.or(part.min_nodes);
                    part.max_nodes = info.max_nodes.or(part.max_nodes);
                    part.default |= info.default;
                }
            }
        }
        summary
    }

    async fn nodes(&self) -> Result<Vec<Node>> {
        let format = format!("--format={NODES_FORMAT}");
        self.json_or_text(
            ("scontrol", &["--json", "show", "node"]),
            nodes_json,
            ("sinfo", &["--noheader", "--Node", "--exact", &format]),
            nodes_text,
        )
        .await
    }

    async fn jobs(&self, history: bool, detail: Option<&str>) -> Result<Vec<Job>> {
        let user = format!("--user={}", self.user().await?);
        let selected = detail.map(|id| format!("--jobs={id}"));
        if history {
            let format = format!("--format={HISTORY_FIELDS}");
            let mut json = vec!["--json", user.as_str(), "--starttime=now-7days"];
            let mut text = vec![
                "--parsable2",
                "--noheader",
                user.as_str(),
                "--starttime=now-7days",
                format.as_str(),
            ];
            if let Some(selected) = &selected {
                json.push(selected);
                text.push(selected);
            } else {
                json.push("--allocations");
                text.push("--allocations");
            }
            self.json_or_text(
                ("sacct", &json),
                |s| jobs_json(s, true),
                ("sacct", &text),
                |s| jobs_text(s, true),
            )
            .await
        } else {
            let format = format!("--Format={QUEUE_FORMAT}");
            self.json_or_text(
                ("squeue", &["--json", &user]),
                |s| jobs_json(s, false),
                ("squeue", &["--noheader", &user, &format]),
                |s| jobs_text(s, false),
            )
            .await
        }
    }

    pub async fn accounting(&self, job: &Job) -> Result<Job> {
        if self.cluster.backend == Backend::Mock {
            return Ok(job.clone());
        }
        ensure!(
            !job.id.is_empty()
                && job.id.len() <= 128
                && job
                    .id
                    .bytes()
                    .all(|b| b.is_ascii_digit() || b"_+".contains(&b)),
            "This job ID cannot be queried individually"
        );
        self.jobs(true, Some(&job.id))
            .await?
            .into_iter()
            .find(|record| record.id == job.id && record.submit == job.submit)
            .context("The accounting record is unavailable")
    }

    async fn json_or_text<T>(
        &self,
        json: (&str, &[&str]),
        parse_json: impl FnOnce(&str) -> Result<T>,
        text: (&str, &[&str]),
        parse_text: impl FnOnce(&str) -> Result<T>,
    ) -> Result<T> {
        match self.execute(json.0, json.1).await {
            Ok(output) => {
                if let Ok(parsed) = parse_json(&output) {
                    return Ok(parsed);
                }
            }
            Err(error) if !error.fallback() => return Err(error.error()),
            Err(_) => {}
        }
        let text = self.execute(text.0, text.1).await.map_err(Failure::error)?;
        parse_text(&text).context("Could not normalize the Slurm response")
    }

    async fn execute(&self, executable: &str, arguments: &[&str]) -> Result<String, Failure> {
        let host = self
            .cluster
            .ssh_host
            .as_deref()
            .ok_or(Failure::Unreachable)?;
        let remote = std::iter::once(executable)
            .chain(arguments.iter().copied())
            .map(shell_argument)
            .collect::<Vec<_>>()
            .join(" ");
        let mut child = Command::new("ssh")
            .args([
                "-T",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=yes",
                host,
                &remote,
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(|_| Failure::Unreachable)?;
        let out = child.stdout.take().ok_or(Failure::Output)?;
        let err = child.stderr.take().ok_or(Failure::Output)?;
        let result = timeout(self.cluster.timeout(), async {
            tokio::try_join!(
                async { child.wait().await.map_err(|_| Failure::Unreachable) },
                limited(out, MAX_OUTPUT),
                limited(err, 256 * 1024),
            )
        })
        .await
        .map_err(|_| Failure::Timeout)??;
        if result.0.success() {
            return String::from_utf8(result.1).map_err(|_| Failure::Output);
        }
        Err(if result.0.code() == Some(255) {
            Failure::Unreachable
        } else {
            Failure::Command
        })
    }
}

async fn limited(stream: impl AsyncRead + Unpin, limit: u64) -> Result<Vec<u8>, Failure> {
    let mut bytes = Vec::new();
    stream
        .take(limit + 1)
        .read_to_end(&mut bytes)
        .await
        .map_err(|_| Failure::Output)?;
    if bytes.len() as u64 > limit {
        Err(Failure::Output)
    } else {
        Ok(bytes)
    }
}

fn shell_argument(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}

pub fn interval(config: &crate::config::Refresh, view: View) -> Duration {
    Duration::from_secs(match view {
        View::Overview => config.partitions_seconds,
        View::Queue => config.jobs_seconds,
        View::History => config.history_seconds,
        View::Nodes => config.nodes_seconds,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quotes_one_remote_argument() {
        assert_eq!(shell_argument("a b; c"), "'a b; c'");
        assert_eq!(shell_argument("it's"), "'it'\"'\"'s'");
    }
}
