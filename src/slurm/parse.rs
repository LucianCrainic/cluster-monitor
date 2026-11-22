use std::collections::BTreeMap;

use anyhow::{Context, Result, ensure};
use chrono::Local;
use serde_json::Value;

use crate::model::{Job, JobState, Node, NodeState, Partition, Stamp, duration, safe};

pub const PARTITIONS_FORMAT: &str = "%P|%a|%l|%D|%F";
pub const NODES_FORMAT: &str = "%N|%P|%T|%c|%C|%m|%e|%G|%E";
pub const QUEUE_FORMAT: &str = concat!(
    "JobID:1|,ArrayJobID:1|,ArrayTaskID:1|,HetJobID:1|,HetJobOffset:1|,",
    "Name:1|,UserName:1|,Partition:1|,State:1|,NumNodes:1|,NodeList:1|,NumCPUs:1|,",
    "MinMemory:1|,tres-alloc:1|,SubmitTime:1|,StartTime:1|,TimeUsed:1|,TimeLimit:1|,Reason:1"
);
pub const HISTORY_FIELDS: &str = concat!(
    "JobIDRaw,JobID,JobName,User,Partition,State,NNodes,NodeList,",
    "ReqCPUS,ReqMem,ReqTRES,Submit,Start,End,Elapsed,Timelimit,Reason"
);

fn records(output: &str, paths: &[&str]) -> Result<Vec<Value>> {
    let mut payload: Value =
        serde_json::from_str(output).map_err(|_| anyhow::anyhow!("Invalid Slurm JSON"))?;
    ensure!(
        payload
            .get("errors")
            .and_then(Value::as_array)
            .is_none_or(Vec::is_empty),
        "Slurm reported a JSON error"
    );
    for path in paths {
        if let Some(items) = payload
            .pointer_mut(path)
            .and_then(Value::as_array_mut)
            .filter(|items| items.iter().all(Value::is_object))
        {
            return Ok(std::mem::take(items));
        }
    }
    anyhow::bail!("Missing Slurm records");
}

fn value<'a>(record: &'a Value, paths: &[&str]) -> Option<&'a Value> {
    paths
        .iter()
        .find_map(|path| record.pointer(path).filter(|value| !value.is_null()))
}

fn number(record: &Value, paths: &[&str]) -> Option<u64> {
    paths
        .iter()
        .filter_map(|path| record.pointer(path))
        .find_map(uint)
}

fn uint(value: &Value) -> Option<u64> {
    if value.get("set").and_then(Value::as_bool) == Some(false)
        || value.get("infinite").and_then(Value::as_bool) == Some(true)
    {
        return None;
    }
    value
        .as_u64()
        .or_else(|| value.as_str()?.trim().parse().ok())
        .or_else(|| value.get("number")?.as_u64())
        .filter(|n| !matches!(*n, 4_294_967_294 | 4_294_967_295 | u64::MAX))
}

fn present(text: &str) -> Option<&str> {
    let text = text.trim();
    let missing = [
        "",
        "-",
        "n/a",
        "none",
        "(null)",
        "null",
        "unknown",
        "not_set",
        "none assigned",
    ];
    (!missing.iter().any(|item| text.eq_ignore_ascii_case(item))).then_some(text)
}

fn text(record: &Value, paths: &[&str]) -> String {
    paths
        .iter()
        .filter_map(|path| record.pointer(path))
        .filter_map(Value::as_str)
        .find_map(present)
        .map_or_else(String::new, safe)
}

fn list(value: Option<&Value>, delimiter: &str) -> String {
    match value {
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(Value::as_str)
            .filter_map(present)
            .map(safe)
            .collect::<Vec<_>>()
            .join(delimiter),
        Some(Value::String(s)) => present(s).map_or_else(String::new, safe),
        _ => String::new(),
    }
}

fn split(value: &str) -> Vec<String> {
    // GRES values may contain commas inside socket masks.
    let mut nesting = 0_u32;
    value
        .split(|c| {
            match c {
                '(' | '[' => nesting += 1,
                ')' | ']' => nesting = nesting.saturating_sub(1),
                ',' if nesting == 0 => return true,
                _ => {}
            }
            false
        })
        .filter_map(present)
        .map(safe)
        .collect()
}

fn time(value: Option<&Value>) -> Option<Stamp> {
    let value = value?;
    uint(value)
        .and_then(|n| i64::try_from(n).ok())
        .filter(|n| *n > 0)
        .map(Stamp::Epoch)
        .or_else(|| Stamp::text(value.as_str()?))
}

fn elapsed(value: Option<&Value>, unit: u64) -> Option<u64> {
    let value = value?;
    uint(value)
        .and_then(|n| n.checked_mul(unit))
        .or_else(|| parse_duration(value.as_str()?, unit))
}

fn parse_duration(input: &str, unit: u64) -> Option<u64> {
    let input = input.trim();
    if let Ok(value) = input.parse::<u64>() {
        return value.checked_mul(unit);
    }
    let (days, clock, has_days) = match input.split_once('-') {
        Some((days, clock)) => (days.parse::<u64>().ok()?, clock, true),
        None => (0, input, false),
    };
    let clock: Vec<u64> = clock
        .split(':')
        .map(str::parse)
        .collect::<Result<_, _>>()
        .ok()?;
    let seconds = match clock.as_slice() {
        [hours, minutes, seconds] => hours
            .saturating_mul(3600)
            .saturating_add(minutes.saturating_mul(60))
            .saturating_add(*seconds),
        [hours, minutes] if has_days => hours
            .saturating_mul(3600)
            .saturating_add(minutes.saturating_mul(60)),
        [minutes, seconds] => minutes.saturating_mul(60).saturating_add(*seconds),
        _ => return None,
    };
    Some(days.saturating_mul(86_400).saturating_add(seconds))
}

fn parse_memory(input: &str, cpus: u64, nodes: u64) -> Option<u64> {
    let input = input.trim().to_ascii_lowercase();
    let (value, scale) = match input.as_bytes().last() {
        Some(b'c') => (&input[..input.len() - 1], cpus.max(1)),
        Some(b'n') => (&input[..input.len() - 1], nodes.max(1)),
        _ => (input.as_str(), 1),
    };
    let pivot = value
        .find(|c: char| !(c.is_ascii_digit() || c == '.'))
        .unwrap_or(value.len());
    let magnitude = value[..pivot].parse::<f64>().ok()?;
    let factor = match value[pivot..]
        .trim()
        .trim_end_matches("ib")
        .trim_end_matches('b')
    {
        "" if value.ends_with('b') => 1.0 / 1_048_576.0,
        "" | "m" => 1.0,
        "k" => 1.0 / 1024.0,
        "g" => 1024.0,
        "t" => 1_048_576.0,
        "p" => 1_073_741_824.0,
        _ => return None,
    };
    if !magnitude.is_finite() {
        return None;
    }
    Some((magnitude * factor * scale as f64).ceil() as u64)
}

fn gpu_name(name: &str) -> bool {
    let name = name.strip_prefix("gres/").unwrap_or(name);
    name == "gpu" || name.starts_with("gpu:")
}

fn gpu_count(source: &str) -> Option<u64> {
    let mut total = None;
    let mut typed: Option<u64> = None;
    for resource in split(source) {
        let core = resource.split('(').next().unwrap_or("");
        let (name, count) = if let Some((name, count)) = core.split_once('=') {
            (name, count)
        } else if let Some((name, count)) = core.rsplit_once(':') {
            (name, count)
        } else {
            continue;
        };
        if !gpu_name(name) {
            continue;
        }
        let Some(count) = count.split('.').next().and_then(|s| s.parse::<u64>().ok()) else {
            continue;
        };
        match name {
            "gres/gpu" | "gpu" => total = Some(count),
            _ => typed = Some(typed.unwrap_or(0).saturating_add(count)),
        }
    }
    total.or(typed)
}

fn gres(value: Option<&Value>) -> Vec<String> {
    match value {
        Some(Value::Array(items)) => items
            .iter()
            .filter_map(|item| {
                if let Some(value) = item.as_str() {
                    return present(value).map(safe);
                }
                let name = item.get("name")?.as_str()?;
                let count = item.get("count").and_then(uint)?;
                Some(format!("{}:{count}", safe(name)))
            })
            .collect(),
        Some(Value::String(value)) => split(value),
        _ => Vec::new(),
    }
}

fn requested_gpus(row: &Value) -> Option<u64> {
    [
        "/tres/requested",
        "/tres_req_str",
        "/tres_per_job",
        "/requested_gres",
        "/tres_alloc_str",
    ]
    .iter()
    .filter_map(|path| row.pointer(path))
    .find_map(|value| {
        if let Some(source) = value.as_str() {
            gpu_count(source)
        } else if let Some(items) = value.as_array() {
            let total = items
                .iter()
                .find(|item| item["name"] == "gpu" || item["type"] == "gpu");
            if let Some(count) = total.and_then(|item| uint(&item["count"])) {
                return Some(count);
            }
            items
                .iter()
                .filter(|item| item["name"].as_str().is_some_and(gpu_name))
                .filter_map(|item| uint(&item["count"]))
                .reduce(u64::saturating_add)
        } else {
            None
        }
    })
}

fn partition(row: &Value) -> Result<Partition> {
    let name = text(row, &["/partition/name", "/name", "/partition_name"]);
    ensure!(!name.is_empty(), "Missing partition name");
    let state = list(
        value(
            row,
            &[
                "/partition/partition/state",
                "/partition/state",
                "/state",
                "/availability",
            ],
        ),
        "+",
    );
    let max_time = value(
        row,
        &[
            "/maximums/time",
            "/partition/maximums/time",
            "/maximum_time",
            "/time_limit",
        ],
    );
    let limit = if max_time.and_then(|v| v.get("infinite")) == Some(&Value::Bool(true)) {
        "Unlimited".into()
    } else if let Some(raw) = max_time
        .and_then(Value::as_str)
        .filter(|s| s.parse::<u64>().is_err())
    {
        safe(raw)
    } else {
        elapsed(max_time, 60).map_or_else(String::new, duration)
    };
    let used = number(
        row,
        &[
            "/nodes/allocation/allocated",
            "/nodes/allocated",
            "/allocated_node_count",
            "/allocated_nodes",
        ],
    )
    .unwrap_or(0);
    let idle = number(
        row,
        &[
            "/nodes/allocation/idle",
            "/nodes/idle",
            "/idle_node_count",
            "/idle_nodes",
        ],
    )
    .unwrap_or(0);
    let other = number(
        row,
        &[
            "/nodes/allocation/other",
            "/nodes/other",
            "/other_node_count",
            "/other_nodes",
        ],
    )
    .unwrap_or(0);
    let flags = list(value(row, &["/flags", "/partition/flags"]), ",");
    Ok(Partition {
        default: name.ends_with('*')
            || flags.split(',').any(|flag| flag == "DEFAULT")
            || value(row, &["/default", "/partition/default"]).and_then(Value::as_bool)
                == Some(true),
        name: name.trim_end_matches('*').into(),
        state,
        total: number(
            row,
            &[
                "/nodes/allocation/total",
                "/nodes/total",
                "/total_nodes",
                "/node_count",
            ],
        )
        .unwrap_or(used.saturating_add(idle).saturating_add(other)),
        idle,
        used,
        other,
        limit,
        qos: list(
            value(
                row,
                &[
                    "/qos/assigned",
                    "/partition/qos/assigned",
                    "/qos/allowed",
                    "/qos",
                    "/quality_of_service",
                ],
            ),
            ", ",
        ),
        hosts: text(
            row,
            &[
                "/nodes/configured",
                "/partition/nodes/configured",
                "/node_names",
            ],
        ),
        min_nodes: number(row, &["/minimums/nodes", "/partition/minimums/nodes"]),
        max_nodes: number(row, &["/maximums/nodes", "/partition/maximums/nodes"]),
    })
}

pub fn partitions_json(output: &str) -> Result<Vec<Partition>> {
    let raw = records(
        output,
        &[
            "/sinfo",
            "/partitions",
            "/partitions/partitions",
            "/sinfo/partitions",
        ],
    )?;
    let mut grouped: BTreeMap<String, Partition> = BTreeMap::new();
    for row in &raw {
        let part = partition(row)?;
        grouped
            .entry(part.name.clone())
            .and_modify(|entry| {
                entry.total = entry.total.saturating_add(part.total);
                entry.used = entry.used.saturating_add(part.used);
                entry.idle = entry.idle.saturating_add(part.idle);
                entry.other = entry.other.saturating_add(part.other);
                entry.default |= part.default;
            })
            .or_insert(part);
    }
    Ok(grouped.into_values().collect())
}

pub fn nodes_json(output: &str) -> Result<Vec<Node>> {
    let raw = records(output, &["/nodes", "/nodes/nodes", "/sinfo/nodes/nodes"])?;
    raw.iter()
        .map(|row| {
            let name = text(row, &["/name", "/node/name", "/hostname"]);
            ensure!(!name.is_empty(), "Missing node name");
            let raw_state = list(value(row, &["/state", "/node/state", "/state_raw"]), "+");
            Ok(Node {
                name,
                partitions: split(&list(
                    value(row, &["/partitions", "/partition_names", "/partition"]),
                    ",",
                )),
                state: NodeState::parse(&raw_state),
                raw_state,
                cpus: number(row, &["/cpus/total", "/cpus", "/cpu_count", "/cpus_total"])
                    .unwrap_or(0),
                allocated_cpus: number(row, &["/cpus/allocated", "/alloc_cpus", "/allocated_cpus"])
                    .unwrap_or(0),
                memory: number(row, &["/memory/maximum", "/real_memory", "/memory_mb"])
                    .unwrap_or(0),
                free_memory: number(row, &["/memory/free", "/free_mem", "/free_memory_mb"]),
                allocated_memory: number(
                    row,
                    &["/memory/allocated", "/alloc_memory", "/allocated_memory_mb"],
                ),
                gpus: gres(value(row, &["/gres/total", "/gres", "/generic_resources"]))
                    .into_iter()
                    .filter(|resource| gpu_name(resource))
                    .collect(),
                features: split(&list(
                    value(row, &["/active_features", "/features/active", "/features"]),
                    ",",
                )),
                reason: text(row, &["/reason/description", "/reason"]),
            })
        })
        .collect()
}

fn job_scope(
    id: &str,
    array: Option<u64>,
    task: String,
    het: Option<u64>,
    offset: Option<u64>,
) -> String {
    if id.contains(['_', '+']) {
        return id.into();
    }
    if let Some(array) = array.filter(|n| *n != 0)
        && !task.is_empty()
    {
        return format!("{array}_{task}");
    }
    if let (Some(het), Some(offset)) = (het.filter(|n| *n != 0), offset) {
        return format!("{het}+{offset}");
    }
    String::new()
}

fn json_job(row: &Value, id: String, history: bool) -> Result<Job> {
    let name = text(row, &["/name", "/job_name", "/job/name"]);
    let user = text(row, &["/user_name", "/user/name", "/user", "/username"]);
    ensure!(!name.is_empty() && !user.is_empty(), "Missing job identity");
    let raw_state = list(
        value(
            row,
            &["/state/current", "/job_state", "/state", "/state_current"],
        ),
        "+",
    );
    let state = JobState::parse(&raw_state);
    let nodes = number(
        row,
        &[
            "/allocation_nodes",
            "/node_count",
            "/nodes/count",
            "/nodes/total",
            "/required/nodes",
        ],
    )
    .unwrap_or(0);
    let cpus = number(
        row,
        &[
            "/required/CPUs",
            "/required/cpus",
            "/requested_cpus",
            "/allocation_cpus",
            "/cpus/total",
            "/cpus",
        ],
    )
    .unwrap_or(0);
    let memory = number(row, &["/requested_memory_mb"])
        .or_else(|| {
            number(row, &["/required/memory_per_node", "/memory_per_node"])
                .filter(|n| *n > 0)
                .and_then(|n| n.checked_mul(nodes.max(1)))
        })
        .or_else(|| {
            number(row, &["/required/memory_per_cpu", "/memory_per_cpu"])
                .filter(|n| *n > 0)
                .and_then(|n| n.checked_mul(cpus.max(1)))
        });
    let submit = time(value(
        row,
        &[
            "/time/submission",
            "/time/submit",
            "/submit_time",
            "/submission_time",
        ],
    ));
    let start = time(value(row, &["/time/start", "/start_time", "/start"]));
    let end = time(value(row, &["/time/end", "/end_time", "/end"]));
    let elapsed = elapsed(
        value(
            row,
            &[
                "/time/elapsed",
                "/elapsed_seconds",
                "/elapsed_time",
                "/elapsed",
                "/time_used",
            ],
        ),
        1,
    )
    .unwrap_or_else(|| {
        if !history && state == JobState::Running {
            start.map_or(0, |stamp| {
                Local::now()
                    .timestamp()
                    .saturating_sub(stamp.order())
                    .max(0) as u64
            })
        } else {
            0
        }
    });
    let scope = job_scope(
        &id,
        number(row, &["/array/job_id", "/array_job_id"]),
        {
            let expression = text(row, &["/array_task_string", "/array/task"]);
            if expression.is_empty() {
                number(row, &["/array/task_id", "/array_task_id"])
                    .map_or_else(String::new, |n| n.to_string())
            } else {
                expression
            }
        },
        number(
            row,
            &["/het/job_id", "/het_job_id", "/heterogeneous_job_id"],
        ),
        number(
            row,
            &[
                "/het/job_offset",
                "/het_job_offset",
                "/heterogeneous_job_offset",
            ],
        ),
    );
    Ok(Job {
        id,
        scope,
        name,
        user,
        partition: text(row, &["/partition/name", "/partition", "/partition_name"]),
        state,
        raw_state,
        reason: text(
            row,
            &[
                "/state/reason/description",
                "/state/reason",
                "/state_reason",
                "/reason/description",
                "/reason",
            ],
        ),
        hosts: list(
            value(
                row,
                &["/node_list", "/nodes/list", "/nodes/names", "/nodes"],
            ),
            ",",
        ),
        nodes,
        cpus,
        gpus: requested_gpus(row),
        memory,
        submit,
        start,
        end,
        elapsed,
        limit: self::elapsed(
            value(
                row,
                &[
                    "/time/limit",
                    "/time_limit",
                    "/time_limit_minutes",
                    "/limit",
                ],
            ),
            60,
        ),
        exit: number(row, &["/exit_code/return_code"]).map_or_else(
            || text(row, &["/exit_code"]),
            |code| {
                format!(
                    "{code}:{}",
                    number(row, &["/exit_code/signal/id"]).unwrap_or(0)
                )
            },
        ),
        peak_memory: None,
        cpu_time: None,
        energy: None,
    })
}

pub fn jobs_json(output: &str, history: bool) -> Result<Vec<Job>> {
    let raw = records(
        output,
        &["/jobs", "/jobs/jobs", "/squeue/jobs", "/sacct/jobs"],
    )?;
    let mut steps: BTreeMap<String, Vec<&Value>> = BTreeMap::new();
    let mut jobs = Vec::new();
    for row in &raw {
        let mut id = text(row, &["/job_id", "/id", "/job/id"]);
        if id.is_empty() {
            id = number(row, &["/job_id", "/id", "/job/id"])
                .context("Missing job ID")?
                .to_string();
        }
        if history && let Some((allocation, _)) = id.split_once('.') {
            steps.entry(allocation.into()).or_default().push(row);
        } else {
            jobs.push((json_job(row, id, history)?, row));
        }
    }
    Ok(jobs
        .into_iter()
        .map(|(mut job, row)| {
            if history {
                let nested = row
                    .get("steps")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten();
                let extra = steps.get(&job.id).into_iter().flatten().copied();
                let rows = || {
                    std::iter::once(row)
                        .chain(nested.clone())
                        .chain(extra.clone())
                };
                job.peak_memory = rows()
                    .filter_map(|item| {
                        number(
                            item,
                            &["/accounting/max_rss_mb", "/max_rss_mb", "/memory/max_rss"],
                        )
                    })
                    .max();
                job.cpu_time = number(
                    row,
                    &[
                        "/accounting/elapsed_cpu_seconds",
                        "/time/total/seconds",
                        "/time/total_cpu",
                    ],
                )
                .or_else(|| {
                    rows()
                        .skip(1)
                        .filter_map(|item| {
                            number(
                                item,
                                &["/accounting/elapsed_cpu_seconds", "/time/total/seconds"],
                            )
                        })
                        .reduce(u64::saturating_add)
                });
                job.energy = number(
                    row,
                    &["/accounting/consumed_energy_joules", "/consumed_energy"],
                )
                .or_else(|| {
                    rows()
                        .skip(1)
                        .filter_map(|item| {
                            number(
                                item,
                                &["/accounting/consumed_energy_joules", "/consumed_energy"],
                            )
                        })
                        .reduce(u64::saturating_add)
                });
            }
            job
        })
        .collect())
}

fn lines<const N: usize>(output: &str) -> impl Iterator<Item = Result<[&str; N]>> {
    output
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| {
            let fields: Vec<_> = line.splitn(N, '|').map(str::trim).collect();
            let mut fields: [&str; N] = fields
                .try_into()
                .map_err(|_| anyhow::anyhow!("Invalid Slurm text fields"))?;
            fields[N - 1] = fields[N - 1].strip_suffix('|').unwrap_or(fields[N - 1]);
            Ok(fields)
        })
}

fn allocations(source: &str) -> Result<[u64; 4]> {
    let counts: Vec<u64> = source
        .split('/')
        .map(str::parse)
        .collect::<Result<_, _>>()
        .map_err(|_| anyhow::anyhow!("Invalid allocation counters"))?;
    counts
        .try_into()
        .map_err(|_| anyhow::anyhow!("Invalid allocation counters"))
}

pub fn partitions_text(output: &str) -> Result<Vec<Partition>> {
    lines::<5>(output)
        .map(|row| {
            let [name, state, limit, total, allocation] = row?;
            let [used, idle, other, fallback] = allocations(allocation)?;
            Ok(Partition {
                name: safe(name.trim_end_matches('*')),
                default: name.ends_with('*'),
                state: safe(state),
                limit: safe(limit),
                total: total.parse().unwrap_or(fallback),
                used,
                idle,
                other,
                ..Partition::default()
            })
        })
        .collect()
}

pub fn nodes_text(output: &str) -> Result<Vec<Node>> {
    let mut nodes: BTreeMap<String, Node> = BTreeMap::new();
    for row in lines::<9>(output) {
        let [
            name,
            partitions,
            state,
            cpus,
            allocation,
            memory,
            free,
            resources,
            reason,
        ] = row?;
        let [used, _, _, fallback] = allocations(allocation)?;
        let partitions: Vec<_> = split(partitions)
            .into_iter()
            .map(|s| s.trim_end_matches('*').to_owned())
            .collect();
        let memory = parse_memory(memory, 1, 1).unwrap_or(0);
        let free_memory = parse_memory(free, 1, 1);
        nodes
            .entry(name.into())
            .and_modify(|node| {
                for partition in &partitions {
                    if !node.partitions.contains(partition) {
                        node.partitions.push(partition.clone());
                    }
                }
            })
            .or_insert(Node {
                name: safe(name),
                partitions,
                state: NodeState::parse(state),
                raw_state: safe(state),
                cpus: cpus.parse().unwrap_or(fallback),
                allocated_cpus: used,
                memory,
                free_memory,
                allocated_memory: free_memory.map(|free| memory.saturating_sub(free)),
                gpus: split(resources)
                    .into_iter()
                    .filter(|resource| gpu_name(resource))
                    .collect(),
                reason: present(reason).map_or_else(String::new, safe),
                ..Node::default()
            });
    }
    Ok(nodes.into_values().collect())
}

pub fn jobs_text(output: &str, history: bool) -> Result<Vec<Job>> {
    if history {
        lines::<17>(output)
            .filter_map(|row| match row {
                Ok(row) if row[0].contains('.') => None,
                other => Some(other),
            })
            .map(|row| {
                let [
                    id,
                    scope,
                    name,
                    user,
                    partition,
                    state,
                    nodes,
                    hosts,
                    cpus,
                    mem,
                    gres,
                    submit,
                    start,
                    end,
                    elapsed,
                    limit,
                    reason,
                ] = row?;
                let (nodes, cpus) = (nodes.parse().unwrap_or(0), cpus.parse().unwrap_or(0));
                Ok(Job {
                    id: safe(id),
                    scope: safe(scope),
                    name: safe(name),
                    user: safe(user),
                    partition: safe(partition),
                    state: JobState::parse(state),
                    raw_state: safe(state),
                    nodes,
                    cpus,
                    hosts: present(hosts).map_or_else(String::new, safe),
                    reason: present(reason).map_or_else(String::new, safe),
                    memory: parse_memory(mem, cpus, nodes),
                    gpus: gpu_count(gres),
                    submit: Stamp::text(submit),
                    start: Stamp::text(start),
                    end: Stamp::text(end),
                    elapsed: parse_duration(elapsed, 1).unwrap_or(0),
                    limit: parse_duration(limit, 60),
                    ..Job::default()
                })
            })
            .collect()
    } else {
        lines::<19>(output)
            .map(|row| {
                let [
                    id,
                    array,
                    task,
                    het,
                    offset,
                    name,
                    user,
                    partition,
                    state,
                    nodes,
                    hosts,
                    cpus,
                    mem,
                    gres,
                    submit,
                    start,
                    elapsed,
                    limit,
                    reason,
                ] = row?;
                let (nodes, cpus) = (nodes.parse().unwrap_or(0), cpus.parse().unwrap_or(0));
                Ok(Job {
                    id: safe(id),
                    scope: job_scope(
                        id,
                        array.parse().ok(),
                        safe(task),
                        het.parse().ok(),
                        offset.parse().ok(),
                    ),
                    name: safe(name),
                    user: safe(user),
                    partition: safe(partition),
                    state: JobState::parse(state),
                    raw_state: safe(state),
                    hosts: present(hosts).map_or_else(String::new, safe),
                    reason: present(reason).map_or_else(String::new, safe),
                    nodes,
                    cpus,
                    memory: parse_memory(mem, cpus, nodes),
                    gpus: gpu_count(gres),
                    submit: Stamp::text(submit),
                    start: Stamp::text(start),
                    elapsed: parse_duration(elapsed, 1).unwrap_or(0),
                    limit: parse_duration(limit, 60),
                    ..Job::default()
                })
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_existing_json_inventory() {
        let fixture = include_str!("../../tests/fixtures/json/sinfo_24_11.json");
        let parts = partitions_json(fixture).unwrap();
        assert_eq!(parts.len(), 2);
        assert_eq!(
            (parts[0].name.as_str(), parts[0].total, parts[0].idle),
            ("compute", 4, 2)
        );
        assert!(parts[0].default);
        assert_eq!(parts[1].limit, "Unlimited");
        let nodes = nodes_json(fixture).unwrap();
        assert_eq!(nodes[1].allocated_cpus, 32);
        assert_eq!(nodes[1].gpus, ["gpu:a100:4"]);
        assert_eq!(nodes[2].state, NodeState::Drained);
    }

    #[test]
    fn parses_existing_text_inventory_and_merges_membership() {
        let parts =
            partitions_text(include_str!("../../tests/fixtures/text/partitions.txt")).unwrap();
        assert_eq!(parts.len(), 3);
        let nodes = nodes_text(include_str!("../../tests/fixtures/text/nodes.txt")).unwrap();
        assert_eq!(nodes.len(), 4);
        let mixed = nodes
            .iter()
            .find(|node| node.state == NodeState::Mixed)
            .unwrap();
        assert!(mixed.partitions.len() >= 2);
    }

    #[test]
    fn normalizes_queue_ids_resources_and_terminal_accounting() {
        let active = jobs_json(
            include_str!("../../tests/fixtures/json/squeue_24_11.json"),
            false,
        )
        .unwrap();
        assert_eq!(active[0].memory, Some(16_384));
        assert_eq!(active[0].gpus, Some(2));
        assert_eq!(active[1].display_id(), "12003_7");
        assert_eq!(active[1].state, JobState::Pending);
        let history = jobs_json(
            include_str!("../../tests/fixtures/json/sacct_24_11.json"),
            true,
        )
        .unwrap();
        assert_eq!(history.len(), 2);
        assert!(history.iter().all(Job::finished));
        assert_eq!(history[1].peak_memory, Some(12_288));
        assert_eq!(history[1].cpu_time, Some(17_280));
        assert_eq!(history[1].exit, "0:0");
    }

    #[test]
    fn text_scopes_and_accounting_steps_are_preserved() {
        let queue = jobs_text(
            include_str!("../../tests/fixtures/text/squeue_scoped_jobs.txt"),
            false,
        )
        .unwrap();
        assert!(queue.iter().any(|job| job.display_id().contains('_')));
        assert!(queue.iter().any(|job| job.display_id().contains('+')));
        let history = jobs_text(
            include_str!("../../tests/fixtures/text/sacct_jobs.txt"),
            true,
        )
        .unwrap();
        assert_eq!(history.len(), 3);
        assert_eq!(history[0].gpus, Some(2));
        assert!(history[2].reason.contains('|'));
    }

    #[test]
    fn json_envelopes_with_errors_do_not_produce_empty_success() {
        assert!(jobs_json(r#"{"errors":[{"code":1}],"jobs":[]}"#, false).is_err());
        assert!(nodes_json(r#"{"errors":[]}"#).is_err());
    }
}
