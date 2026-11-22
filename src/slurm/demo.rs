use crate::model::{Data, Job, JobState, Node, NodeState, Partition, Snapshot, Stamp, View};
use chrono::Local;

pub fn snapshot(view: View, user: &str) -> Snapshot {
    let account = if user == "current" {
        "researcher"
    } else {
        user
    };
    let data = match view {
        View::Overview => {
            let nodes = nodes();
            let partitions = [
                ("compute", "2d 00:00:00", "normal"),
                ("gpu", "1d 00:00:00", "accelerated"),
                ("short", "01:00:00", "interactive"),
                ("memory", "1d 00:00:00", "highmem"),
                ("debug", "00:30:00", "debug"),
                ("long", "7d 00:00:00", "batch"),
                ("maintenance", "01:00:00", "admin"),
            ]
            .into_iter()
            .map(|(name, limit, qos)| {
                let members: Vec<_> = nodes
                    .iter()
                    .filter(|n| n.partitions.iter().any(|p| p == name))
                    .collect();
                let total = members.len() as u64;
                let idle = members
                    .iter()
                    .filter(|n| n.state == NodeState::Idle)
                    .count() as u64;
                let used = members.iter().filter(|n| n.state.active()).count() as u64;
                Partition {
                    name: name.into(),
                    state: if name == "maintenance" { "DOWN" } else { "UP" }.into(),
                    default: name == "compute",
                    total,
                    idle,
                    used,
                    other: total - idle - used,
                    limit: limit.into(),
                    qos: qos.into(),
                    hosts: members
                        .iter()
                        .map(|n| n.name.as_str())
                        .collect::<Vec<_>>()
                        .join(", "),
                    min_nodes: Some(1),
                    max_nodes: Some(total),
                }
            })
            .collect();
            Data::Overview { partitions, nodes }
        }
        View::Nodes => Data::Nodes(nodes()),
        View::Queue => Data::Jobs(jobs(account, false)),
        View::History => Data::Jobs(jobs(account, true)),
    };
    Snapshot {
        version: "25.11.8".into(),
        data,
    }
}

fn nodes() -> Vec<Node> {
    (1..=48)
        .map(|i| {
            let (prefix, mut partitions, cpus, memory, gpus) = match i {
                1..=24 => ("cpu", vec!["compute", "long"], 128, 262_144, Vec::new()),
                25..=32 => ("gpu", vec!["gpu"], 64, 524_288, vec!["gpu:a100:4".into()]),
                33..=38 => ("mem", vec!["memory", "long"], 96, 1_048_576, Vec::new()),
                39..=44 => ("cpu", vec!["short", "debug"], 64, 131_072, Vec::new()),
                _ => (
                    "cpu",
                    vec!["compute", "maintenance"],
                    128,
                    262_144,
                    Vec::new(),
                ),
            };
            if i % 9 == 0 {
                partitions.push("short");
            }
            let (state, allocated, reason) = match (i, i % 8) {
                (45..=48, _) => (NodeState::Down, 0, "Maintenance window"),
                (_, 0) => (NodeState::Drained, 0, "Hardware inspection"),
                (_, 1 | 6) => (NodeState::Idle, 0, ""),
                (_, 2 | 5) => (NodeState::Mixed, cpus / 2, ""),
                _ => (NodeState::Allocated, cpus, ""),
            };
            Node {
                name: format!("{prefix}-{i:03}"),
                partitions: partitions.into_iter().map(str::to_owned).collect(),
                state,
                raw_state: state.label().to_ascii_uppercase(),
                cpus,
                allocated_cpus: allocated,
                memory,
                allocated_memory: Some(memory / cpus * allocated),
                free_memory: Some(memory - memory / cpus * allocated),
                gpus,
                features: vec![
                    if memory >= 1_048_576 {
                        "high-memory"
                    } else {
                        "standard"
                    }
                    .into(),
                ],
                reason: reason.into(),
            }
        })
        .collect()
}

fn jobs(user: &str, history: bool) -> Vec<Job> {
    let samples = [
        ("protein-sim", "compute", "cpu-003", 64, 0),
        ("train-model", "gpu", "gpu-027", 32, 2),
        ("parameter-scan", "compute", "cpu-004", 16, 0),
        ("genome-align", "memory", "mem-034", 48, 0),
        ("mesh-refine", "long", "cpu-015", 96, 0),
        ("spectral-analysis", "compute", "cpu-011", 16, 0),
        ("validate-checkpoint", "short", "cpu-041", 8, 0),
        ("gpu-sweep", "gpu", "gpu-028", 32, 4),
        ("preprocess", "compute", "cpu-010", 32, 0),
        ("ensemble-run", "long", "cpu-012", 64, 0),
        ("benchmark-io", "debug", "cpu-044", 4, 0),
    ];
    let now = Local::now().timestamp();
    samples
        .into_iter()
        .enumerate()
        .map(|(i, (name, partition, host, cpus, gpus))| {
            let state = if history {
                match i % 7 {
                    1 => JobState::Failed,
                    4 => JobState::Timeout,
                    5 => JobState::Cancelled,
                    _ => JobState::Completed,
                }
            } else if i == 8 || i == 10 {
                JobState::Pending
            } else if i == 9 {
                JobState::Suspended
            } else {
                JobState::Running
            };
            let ago = i as i64 * 1130;
            let elapsed = 1440 + i as u64 * 320;
            let start = now - ago - elapsed as i64;
            let pending = state == JobState::Pending;
            let id = if history { 12480 - i } else { 12501 + i };
            Job {
                id: id.to_string(),
                scope: if i == 9 {
                    format!("{id}_7")
                } else {
                    String::new()
                },
                name: name.into(),
                user: user.into(),
                partition: partition.into(),
                state,
                raw_state: state.label().to_ascii_uppercase(),
                reason: if pending {
                    if i == 8 { "Resources" } else { "Priority" }.into()
                } else {
                    String::new()
                },
                hosts: if pending { String::new() } else { host.into() },
                nodes: 1,
                cpus,
                gpus: Some(gpus),
                memory: Some(4096 * cpus),
                submit: Some(Stamp::Epoch(start - 290)),
                start: (!pending).then_some(Stamp::Epoch(start)),
                end: history.then_some(Stamp::Epoch(now - ago)),
                elapsed: if pending { 0 } else { elapsed },
                limit: Some(43_200),
                exit: if history {
                    if state.failed() { "1:0" } else { "0:0" }.into()
                } else {
                    String::new()
                },
                peak_memory: history.then_some(1720 * cpus),
                cpu_time: history.then_some(elapsed * cpus),
                energy: None,
            }
        })
        .collect()
}
