use chrono::{DateTime, Local, NaiveDateTime};
use std::fmt::{self, Display};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum JobState {
    Running,
    Pending,
    Suspended,
    Completed,
    Failed,
    Cancelled,
    Timeout,
    OutOfMemory,
    #[default]
    Unknown,
}

impl JobState {
    pub fn parse(raw: &str) -> Self {
        match raw
            .split(['+', ' '])
            .next()
            .unwrap_or("")
            .trim_end_matches(['*', '~', '$', '@', '#', '!', '%', '^'])
            .to_ascii_uppercase()
            .as_str()
        {
            "RUNNING" | "COMPLETING" | "RESIZING" | "R" | "CG" => Self::Running,
            "PENDING" | "CONFIGURING" | "PD" => Self::Pending,
            "SUSPENDED" | "STOPPED" | "S" => Self::Suspended,
            "COMPLETED" | "CD" => Self::Completed,
            "CANCELLED" | "CA" => Self::Cancelled,
            "TIMEOUT" | "TO" => Self::Timeout,
            "OUT_OF_MEMORY" | "OOM" => Self::OutOfMemory,
            "FAILED" | "BOOT_FAIL" | "DEADLINE" | "NODE_FAIL" | "PREEMPTED" | "REVOKED"
            | "SPECIAL_EXIT" | "F" => Self::Failed,
            _ => Self::Unknown,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Running => "Running",
            Self::Pending => "Pending",
            Self::Suspended => "Suspended",
            Self::Completed => "Completed",
            Self::Failed => "Failed",
            Self::Cancelled => "Cancelled",
            Self::Timeout => "Timeout",
            Self::OutOfMemory => "Out of memory",
            Self::Unknown => "Unknown",
        }
    }

    pub fn failed(self) -> bool {
        matches!(self, Self::Failed | Self::Timeout | Self::OutOfMemory)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum NodeState {
    Idle,
    Mixed,
    Allocated,
    Completing,
    Drained,
    Down,
    #[default]
    Unknown,
}

impl NodeState {
    pub fn parse(raw: &str) -> Self {
        let base = raw.trim_end_matches(['*', '~', '#', '!', '%', '$', '@', '^', '-']);
        let suffix = &raw[base.len()..];
        let upper = base.to_ascii_uppercase();
        let states: Vec<_> = upper.split(['+', ',', ' ']).collect();
        let has = |names: &[&str]| states.iter().any(|s| names.contains(s));
        if suffix.contains(['*', '~', '#', '!', '%', '@', '^'])
            || has(&[
                "DOWN",
                "ERROR",
                "ERR",
                "INVAL",
                "INVALID",
                "NO_RESPOND",
                "POWERED_DOWN",
                "POWERING_DOWN",
                "POWER_DOWN",
            ])
        {
            Self::Down
        } else if suffix.contains('$')
            || has(&[
                "DRAIN",
                "DRAINED",
                "DRAINING",
                "DRNG",
                "MAINT",
                "MAINTENANCE",
                "FAIL",
                "FAILING",
                "FAILG",
            ])
        {
            Self::Drained
        } else if suffix.contains('-') {
            Self::Unknown
        } else if has(&["COMPLETING", "COMP"]) {
            Self::Completing
        } else if has(&["MIXED", "MIX"]) {
            Self::Mixed
        } else if has(&["ALLOCATED", "ALLOC"]) {
            Self::Allocated
        } else if has(&["IDLE"])
            && !has(&[
                "BLOCKED",
                "CLOUD",
                "FUTURE",
                "NPC",
                "PERFCTRS",
                "PLANNED",
                "POWERING_UP",
                "REBOOT_ISSUED",
                "REBOOT_REQUESTED",
                "RESERVED",
            ])
        {
            Self::Idle
        } else {
            Self::Unknown
        }
    }

    pub fn active(self) -> bool {
        matches!(self, Self::Mixed | Self::Allocated | Self::Completing)
    }
    pub fn label(self) -> &'static str {
        match self {
            Self::Idle => "Idle",
            Self::Mixed => "Mixed",
            Self::Allocated => "Allocated",
            Self::Completing => "Completing",
            Self::Drained => "Drained",
            Self::Down => "Down",
            Self::Unknown => "Unknown",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub enum Stamp {
    Epoch(i64),
    Local(NaiveDateTime),
}

impl Stamp {
    pub fn text(text: &str) -> Option<Self> {
        DateTime::parse_from_rfc3339(text)
            .map(|value| Self::Epoch(value.timestamp()))
            .ok()
            .or_else(|| {
                NaiveDateTime::parse_from_str(text, "%Y-%m-%dT%H:%M:%S")
                    .ok()
                    .map(Self::Local)
            })
    }

    pub fn order(self) -> i64 {
        match self {
            Self::Epoch(value) => value,
            Self::Local(value) => value.and_utc().timestamp(),
        }
    }

    pub fn format(self, format: &str) -> String {
        match self {
            Self::Epoch(epoch) => DateTime::from_timestamp(epoch, 0).map_or_else(
                || "—".into(),
                |time| time.with_timezone(&Local).format(format).to_string(),
            ),
            Self::Local(time) => time.format(format).to_string(),
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Job {
    pub id: String,
    pub scope: String,
    pub name: String,
    pub user: String,
    pub partition: String,
    pub state: JobState,
    pub raw_state: String,
    pub reason: String,
    pub hosts: String,
    pub nodes: u64,
    pub cpus: u64,
    pub gpus: Option<u64>,
    pub memory: Option<u64>,
    pub submit: Option<Stamp>,
    pub start: Option<Stamp>,
    pub end: Option<Stamp>,
    pub elapsed: u64,
    pub limit: Option<u64>,
    pub exit: String,
    pub peak_memory: Option<u64>,
    pub cpu_time: Option<u64>,
    pub energy: Option<u64>,
}

impl Job {
    pub fn finished(&self) -> bool {
        match self.state {
            JobState::Running | JobState::Pending | JobState::Suspended => false,
            JobState::Unknown => self
                .end
                .is_some_and(|end| end.order() <= Local::now().timestamp()),
            _ => true,
        }
    }

    pub fn recency(&self) -> i64 {
        self.end
            .or(self.start)
            .or(self.submit)
            .map_or(0, Stamp::order)
    }

    pub fn display_id(&self) -> &str {
        if self.scope.is_empty() {
            &self.id
        } else {
            &self.scope
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Node {
    pub name: String,
    pub partitions: Vec<String>,
    pub state: NodeState,
    pub raw_state: String,
    pub cpus: u64,
    pub allocated_cpus: u64,
    pub memory: u64,
    pub free_memory: Option<u64>,
    pub allocated_memory: Option<u64>,
    pub gpus: Vec<String>,
    pub features: Vec<String>,
    pub reason: String,
}

#[derive(Clone, Debug, Default)]
pub struct Partition {
    pub name: String,
    pub state: String,
    pub default: bool,
    pub total: u64,
    pub idle: u64,
    pub used: u64,
    pub other: u64,
    pub limit: String,
    pub qos: String,
    pub hosts: String,
    pub min_nodes: Option<u64>,
    pub max_nodes: Option<u64>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum View {
    Overview,
    Queue,
    History,
    Nodes,
}

impl View {
    pub const ALL: [Self; 4] = [Self::Overview, Self::Queue, Self::History, Self::Nodes];
    pub const fn index(self) -> usize {
        match self {
            Self::Overview => 0,
            Self::Queue => 1,
            Self::History => 2,
            Self::Nodes => 3,
        }
    }
    pub fn next(self, reverse: bool) -> Self {
        Self::ALL[(self.index() + if reverse { 3 } else { 1 }) % Self::ALL.len()]
    }
}
impl Display for View {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Overview => "Overview",
            Self::Queue => "Queue",
            Self::History => "History",
            Self::Nodes => "Nodes",
        })
    }
}

#[derive(Debug)]
pub enum Data {
    Overview {
        partitions: Vec<Partition>,
        nodes: Vec<Node>,
    },
    Jobs(Vec<Job>),
    Nodes(Vec<Node>),
}

pub struct Snapshot {
    pub version: String,
    pub data: Data,
}

pub fn safe(text: &str) -> String {
    text.chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect()
}

pub fn quantity(value: u64) -> String {
    let digits = value.to_string();
    let mut result = String::with_capacity(digits.len() + digits.len() / 3);
    for (i, digit) in digits.chars().enumerate() {
        if i != 0 && (digits.len() - i).is_multiple_of(3) {
            result.push(',');
        }
        result.push(digit);
    }
    result
}

pub fn duration(seconds: u64) -> String {
    let hours = seconds / 3600;
    let clock = format!(
        "{:02}:{:02}:{:02}",
        hours % 24,
        seconds / 60 % 60,
        seconds % 60
    );
    if hours >= 24 {
        format!("{}d {clock}", hours / 24)
    } else {
        clock
    }
}

pub fn memory(mib: u64) -> String {
    match mib {
        n if n >= 1024_u64.pow(2) => format!("{:.1} TiB", n as f64 / 1024_f64.powi(2)),
        n if n >= 1024 => format!("{:.1} GiB", n as f64 / 1024.0),
        n => format!("{n} MiB"),
    }
}
