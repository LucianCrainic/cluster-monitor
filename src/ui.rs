use ratatui::{
    Frame,
    layout::{
        Alignment,
        Constraint::{self, Fill, Length, Min},
        Layout, Position, Rect,
    },
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{
        Block, BorderType, Cell, Clear, HighlightSpacing, Padding, Paragraph, Row, Scrollbar,
        ScrollbarOrientation, ScrollbarState, Table, Wrap,
    },
};

use crate::{
    app::{App, Hits, Menu, Overlay, Pane, Record},
    config::Backend,
    model::{Data, JobState, NodeState, Stamp, View, duration, memory, quantity},
};

mod heatmap;

const TEXT: Color = Color::Reset;
const ACCENT: Color = Color::Cyan;
const MAGENTA: Color = Color::Magenta;
const BLUE: Color = Color::Blue;
const GREEN: Color = Color::Green;
const AMBER: Color = Color::Yellow;
const RED: Color = Color::Red;
const DIM: Style = Style::new().add_modifier(Modifier::DIM);
const FOCUSED: Style = Style::new().fg(ACCENT).add_modifier(Modifier::BOLD);

pub fn draw(frame: &mut Frame<'_>, app: &mut App) {
    let area = frame.area();
    app.hits = Hits::default();
    if area.width < 36 || area.height < 12 {
        frame.render_widget(
            Paragraph::new("Resize your terminal  ·  q quit").centered(),
            area,
        );
        return;
    }

    let [masthead, workspace, status, footer] =
        Layout::vertical([Length(1), Min(5), Length(1), Length(1)]).areas(inset(area, 1, 0));
    header(frame, app, masthead);

    if workspace.width >= 116 && workspace.height >= 24 {
        let [rail, _, table] =
            Layout::horizontal([Length(32), Length(1), Fill(1)]).areas(workspace);
        let [views, totals, preview] =
            Layout::vertical([Length(6), Length(8), Fill(1)]).areas(rail);
        navigation(frame, app, views, true);
        summary(frame, app.pane(), app.view, totals, true);
        inspector(frame, app, preview);
        records_workspace(frame, app, table, false);
    } else {
        responsive_workspace(frame, app, workspace);
    }
    status_bar(frame, app, status);
    shortcuts(frame, app, footer);
    if let Some(overlay) = &app.overlay {
        draw_overlay(frame, overlay, area, &mut app.hits);
    }
}

fn responsive_workspace(frame: &mut Frame<'_>, app: &mut App, workspace: Rect) {
    let content = if workspace.width >= 98 && workspace.height >= 16 {
        let [rail, _, main] = Layout::horizontal([Length(25), Length(1), Fill(1)]).areas(workspace);
        let [views, summary_area] = Layout::vertical([Length(6), Length(8)]).areas(rail);
        navigation(frame, app, views, true);
        summary(frame, app.pane(), app.view, summary_area, true);
        main
    } else {
        let metrics_height = if workspace.height >= 15 { 4 } else { 0 };
        let [views, summary_area, main] =
            Layout::vertical([Length(3), Length(metrics_height), Fill(1)]).areas(workspace);
        navigation(frame, app, views, false);
        if metrics_height > 0 {
            summary(frame, app.pane(), app.view, summary_area, false);
        }
        main
    };

    records_workspace(frame, app, content, true);
}

fn records_workspace(frame: &mut Frame<'_>, app: &mut App, area: Rect, show_preview: bool) {
    if app.view == View::Overview && area.height >= 13 {
        let table_rows = app.pane().matches.len().saturating_add(4);
        let table_height = table_rows.clamp(7, usize::from(area.height) * 3 / 5) as u16;
        let [table, heatmap_area] = Layout::vertical([Length(table_height), Fill(1)]).areas(area);
        records_pane(frame, app, table);
        app.hits.heatmap = heatmap::draw(frame, app.pane(), heatmap_area);
    } else if show_preview && area.width >= 64 && area.height >= 22 {
        let [table, preview] = Layout::vertical([Fill(1), Length(10)]).areas(area);
        records_pane(frame, app, table);
        inspector(frame, app, preview);
    } else {
        records_pane(frame, app, area);
    }
}

fn pane(title: &str, focused: bool) -> Block<'static> {
    Block::bordered()
        .border_type(BorderType::Rounded)
        .border_style(if focused { FOCUSED } else { DIM })
        .title(Line::from(bold(
            format!(" {title} "),
            if focused { ACCENT } else { TEXT },
        )))
}

fn header(frame: &mut Frame<'_>, app: &mut App, area: Rect) {
    let [brand, cluster] = Layout::horizontal([Length(16), Fill(1)]).areas(area);
    frame.render_widget(
        Line::from(vec![bold("slurm", ACCENT), muted(" monitor")]),
        brand,
    );
    let source = &app.sources[app.cluster].cluster;
    let (badge, color) = if source.backend == Backend::Mock {
        ("demo", MAGENTA)
    } else {
        ("ssh", ACCENT)
    };
    let mut labels = vec![fg(&source.name, TEXT)];
    if area.width >= 74 && !app.version.is_empty() {
        labels.push(muted(format!("  ·  Slurm {}", app.version)));
    }
    labels.push(muted("  ·  "));
    labels.push(bold(badge, color));
    if app.sources.len() > 1 {
        labels.push(muted(" ▾"));
    }
    frame.render_widget(Line::from(labels).right_aligned(), cluster);
    app.hits.cluster = cluster;
}

fn navigation(frame: &mut Frame<'_>, app: &mut App, area: Rect, vertical: bool) {
    let block = pane("Views", false);
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let slots = if vertical {
        Layout::vertical([Length(1); 4]).split(inner)
    } else {
        Layout::horizontal([Fill(1); 4]).split(inner)
    };
    for view in View::ALL {
        let index = view.index();
        let active = view == app.view;
        let label = if !vertical && inner.width < 51 && view == View::Overview {
            "Cluster".into()
        } else {
            view.to_string()
        };
        let mut spans = Vec::new();
        if vertical {
            spans.push(fg(if active { " ▸ " } else { "   " }, ACCENT));
        }
        spans.push(if active {
            bold(format!("{} ", index + 1), ACCENT)
        } else {
            muted(format!("{} ", index + 1))
        });
        spans.push(if active {
            bold(label, TEXT)
        } else {
            fg(label, TEXT)
        });
        let line = Line::from(spans);
        let line = if vertical { line } else { line.centered() };
        frame.render_widget(line, slots[index]);
        app.hits.tabs[index] = slots[index];
    }
}

fn records_pane(frame: &mut Frame<'_>, app: &mut App, area: Rect) {
    let title = match app.view {
        View::Overview => "Partitions",
        View::Queue => "Active jobs",
        View::History => "Job history · 7 days",
        View::Nodes => "Node inventory",
    };
    let snapshot = app.pane();
    let count = if !snapshot.is_filtered() {
        quantity(snapshot.len() as u64)
    } else {
        format!(
            "{}/{}",
            quantity(snapshot.matches.len() as u64),
            quantity(snapshot.len() as u64)
        )
    };
    let count = format!(" {count} records ");
    let mut block = pane(title, app.overlay.is_none());
    if title.chars().count() + count.len() + 5 <= usize::from(area.width) {
        block = block.title(Line::from(muted(count)).right_aligned());
    }
    let inside = block.inner(area);
    frame.render_widget(block, area);
    let [command, body] = Layout::vertical([Length(1), Fill(1)]).areas(inside);
    filter(frame, app, command);
    draw_table(frame, app, body);
}

struct Metric(&'static str, String, Color);

fn summary(frame: &mut Frame<'_>, data: &Pane, view: View, area: Rect, vertical: bool) {
    let (metrics, stats) = metrics(data, view);
    let title = match view {
        View::Overview => "Capacity",
        View::Queue => "Queue totals",
        View::History => "Outcomes",
        View::Nodes => "Resources",
    };
    let block = pane(title, false);
    let inside = block.inner(area);
    frame.render_widget(block, area);
    if vertical {
        let inside = inset(inside, 1, 0);
        let [list, gauge] = Layout::vertical([Length(4), Fill(1)]).areas(inside);
        for (index, Metric(label, value, color)) in metrics.into_iter().enumerate() {
            let line = Rect::new(list.x, list.y + index as u16, list.width, 1).intersection(list);
            let [label_area, value_area] =
                Layout::horizontal([Fill(1), Length(value.len() as u16)]).areas(line);
            frame.render_widget(Line::from(muted(label)), label_area);
            frame.render_widget(Line::from(bold(value, color)).right_aligned(), value_area);
        }
        if let Some((label, segments)) = stats {
            frame.render_widget(
                Paragraph::new(vec![
                    Line::from(muted(label)),
                    meter(&segments, gauge.width),
                ]),
                gauge,
            );
        }
    } else {
        let slots = Layout::horizontal([Fill(1); 4]).split(inside);
        for (slot, Metric(label, value, color)) in slots.iter().zip(metrics) {
            let inside = inset(*slot, 1, 0);
            frame.render_widget(
                Paragraph::new(vec![
                    Line::from(bold(value, color)),
                    Line::from(muted(label)),
                ]),
                inside,
            );
        }
    }
}

type Breakdown = (&'static str, [(u64, Color); 3]);

fn metrics(pane: &Pane, view: View) -> ([Metric; 4], Option<Breakdown>) {
    let n = |label, value, color| Metric(label, quantity(value), color);
    match pane.data.as_ref() {
        Some(Data::Overview { nodes, .. }) => {
            let total = nodes.len() as u64;
            let active = nodes.iter().filter(|node| node.state.active()).count() as u64;
            let idle = nodes
                .iter()
                .filter(|node| node.state == NodeState::Idle)
                .count() as u64;
            let other = total - active - idle;
            (
                [
                    n("Total nodes", total, ACCENT),
                    n("Allocated", active, BLUE),
                    n("Idle", idle, GREEN),
                    n("Unavailable", other, AMBER),
                ],
                Some((
                    "Node allocation",
                    [(active, BLUE), (idle, GREEN), (other, AMBER)],
                )),
            )
        }
        Some(Data::Jobs(jobs)) => {
            let history = view == View::History;
            let (label, first, second, measured, name, color, meter) = if history {
                (
                    "Finished",
                    "Completed",
                    "Failed",
                    JobState::Completed,
                    "Other outcomes",
                    RED,
                    "Job outcomes",
                )
            } else {
                (
                    "Queue size",
                    "Running",
                    "Pending",
                    JobState::Running,
                    "Other states",
                    AMBER,
                    "Queue mix",
                )
            };
            let green = jobs.iter().filter(|job| job.state == measured).count() as u64;
            let alert = jobs
                .iter()
                .filter(|job| {
                    if history {
                        job.state.failed()
                    } else {
                        job.state == JobState::Pending
                    }
                })
                .count() as u64;
            let total = jobs.len() as u64;
            let other = total - green - alert;
            (
                [
                    n(label, total, ACCENT),
                    n(first, green, GREEN),
                    n(second, alert, color),
                    n(name, other, MAGENTA),
                ],
                Some((meter, [(green, GREEN), (alert, color), (other, MAGENTA)])),
            )
        }
        Some(Data::Nodes(nodes)) => {
            let total: u64 = nodes.iter().map(|n| n.cpus).sum();
            let used: u64 = nodes.iter().map(|n| n.allocated_cpus.min(n.cpus)).sum();
            let gpu = nodes.iter().filter(|n| !n.gpus.is_empty()).count() as u64;
            let unavailable = nodes
                .iter()
                .filter(|n| matches!(n.state, NodeState::Down | NodeState::Drained))
                .count() as u64;
            (
                [
                    Metric(
                        "CPU use",
                        format!("{}/{}", quantity(used), quantity(total)),
                        BLUE,
                    ),
                    Metric(
                        "Total memory",
                        memory(nodes.iter().map(|n| n.memory).sum()),
                        MAGENTA,
                    ),
                    n("GPU nodes", gpu, GREEN),
                    n("Drained / down", unavailable, AMBER),
                ],
                Some(("CPU use", [(used, BLUE), (total - used, TEXT), (0, TEXT)])),
            )
        }
        None => {
            let labels = match view {
                View::Overview => ["Total nodes", "Allocated", "Idle", "Unavailable"],
                View::Queue => ["Queue size", "Running", "Pending", "Other states"],
                View::History => ["Finished", "Completed", "Failed", "Other outcomes"],
                View::Nodes => [
                    "CPU allocation",
                    "Total memory",
                    "GPU nodes",
                    "Drained / down",
                ],
            };
            (labels.map(|label| Metric(label, "—".into(), TEXT)), None)
        }
    }
}

fn filter(frame: &mut Frame<'_>, app: &mut App, area: Rect) {
    let sort_width = if area.width >= 60 { 17 } else { 0 };
    let state_width = if area.width >= 60 { 22 } else { 14 };
    let [search, state, sort] =
        Layout::horizontal([Fill(1), Length(state_width), Length(sort_width)])
            .areas(inset(area, 1, 0));
    let data = app.pane();
    let visible: String = data
        .filter
        .chars()
        .rev()
        .take(search.width.saturating_sub(4) as usize)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    let input = if visible.is_empty() && !app.editing {
        muted("Filter records")
    } else {
        fg(visible, TEXT)
    };
    let line = Line::from(vec![bold("/ ", ACCENT), input]);
    let cursor_offset = line.width().min(search.width.saturating_sub(1) as usize);
    frame.render_widget(line, search);
    let state_text = match &data.state_filter {
        Some(state) => bold(format!(" {state}"), ACCENT),
        None => muted(" All states"),
    };
    frame.render_widget(
        Line::from(vec![bold("f", ACCENT), state_text, muted(" ▾")]),
        state,
    );
    if sort.width > 0 {
        frame.render_widget(
            Line::from(vec![
                bold("s ", ACCENT),
                muted(format!("Sort: {}", data.sort.label())),
            ])
            .right_aligned(),
            sort,
        );
    }
    if app.editing && app.overlay.is_none() {
        frame.set_cursor_position(Position::new(search.x + cursor_offset as u16, search.y));
    }
    app.hits.filter = search;
    app.hits.state_filter = state;
    app.hits.sort = sort;
}

struct Column {
    label: &'static str,
    width: Constraint,
    shown_at: u16,
}
const fn col(label: &'static str, width: Constraint, shown_at: u16) -> Column {
    Column {
        label,
        width,
        shown_at,
    }
}

fn columns(view: View) -> &'static [Column] {
    const OVERVIEW: &[Column] = &[
        col("PARTITION", Fill(1), 0),
        col("STATE", Length(8), 0),
        col("ALLOCATION", Length(12), 42),
        col("NODES", Length(5), 0),
        col("IDLE", Length(5), 49),
        col("USED", Length(5), 59),
        col("OTHER", Length(5), 66),
        col("LIMIT", Length(12), 72),
    ];
    const QUEUE: &[Column] = &[
        col("JOB ID", Length(10), 0),
        col("JOB", Fill(2), 0),
        col("STATE", Length(13), 0),
        col("PARTITION", Length(10), 55),
        col("ELAPSED", Length(9), 45),
        col("NODE/WHY", Length(10), 73),
    ];
    const HISTORY: &[Column] = &[
        col("JOB ID", Length(10), 0),
        col("JOB", Fill(1), 0),
        col("STATE", Length(13), 0),
        col("PARTITION", Length(10), 55),
        col("ELAPSED", Length(9), 45),
        col("ENDED", Length(12), 73),
    ];
    const NODES: &[Column] = &[
        col("NODE", Fill(1), 0),
        col("STATE", Length(10), 0),
        col("PARTITIONS", Fill(1), 48),
        col("CPUS USED", Length(10), 0),
        col("MEMORY", Length(10), 56),
        col("GPUS", Fill(1), 72),
    ];
    match view {
        View::Overview => OVERVIEW,
        View::Queue => QUEUE,
        View::History => HISTORY,
        View::Nodes => NODES,
    }
}

fn draw_table(frame: &mut Frame<'_>, app: &mut App, area: Rect) {
    if area.height < 2 {
        return;
    }
    let view = app.view;
    let pane = app.pane_mut();
    if pane.matches.is_empty() {
        let text = if pane.error.is_some() && pane.data.is_none() {
            "Data unavailable · press r to retry"
        } else if pane.data.is_none() {
            "Fetching Slurm data…"
        } else if pane.is_filtered() {
            "No records match · Esc clears filters"
        } else {
            match view {
                View::Queue => "No active jobs for the configured user",
                View::History => "No finished jobs for the configured user",
                View::Overview => "Slurm returned no partitions",
                View::Nodes => "Slurm returned no nodes",
            }
        };
        frame.render_widget(
            Paragraph::new(muted(text))
                .centered()
                .block(Block::new().padding(Padding::top(1))),
            area,
        );
        return;
    }
    let table_area = Rect::new(area.x, area.y, area.width - 1, area.height);
    let columns = columns(view);
    let visible: Vec<_> = columns
        .iter()
        .enumerate()
        .filter(|(_, col)| table_area.width >= col.shown_at)
        .collect();
    let widths = visible.iter().map(|(_, col)| col.width);
    let header = Row::new(visible.iter().map(|(_, col)| col.label))
        .style(Style::new().add_modifier(Modifier::BOLD));
    let rows = pane.matches.iter().filter_map(|&index| {
        let cells = row_cells(pane.row(index)?, view);
        Some(Row::new(
            visible.iter().map(|(index, _)| cells[*index].clone()),
        ))
    });
    let table = Table::new(rows, widths)
        .header(header)
        .column_spacing(1)
        .row_highlight_style(Style::new().add_modifier(Modifier::BOLD))
        .highlight_symbol(Span::styled("▎ ", Style::new().fg(ACCENT)))
        .highlight_spacing(HighlightSpacing::Always);
    frame.render_stateful_widget(table, table_area, &mut pane.table);
    let body = Rect::new(area.x, area.y + 1, area.width, area.height - 1);
    if pane.matches.len() > body.height as usize {
        let mut scroll = ScrollbarState::new(pane.matches.len())
            .position(pane.table.selected().unwrap_or(0))
            .viewport_content_length(body.height as usize);
        frame.render_stateful_widget(
            Scrollbar::new(ScrollbarOrientation::VerticalRight)
                .begin_symbol(None)
                .end_symbol(None)
                .track_style(DIM)
                .thumb_style(Style::new().fg(ACCENT)),
            body,
            &mut scroll,
        );
    }
    app.hits.body = body;
}

fn row_cells(record: Record<'_>, view: View) -> Vec<Cell<'static>> {
    let cell = |text: String, color| Cell::new(fg(text, color));
    let quiet = |text: String| Cell::new(muted(text));
    match record {
        Record::Partition(part) => {
            let title = if part.default {
                Line::from(vec![fg(part.name.clone(), TEXT), fg(" *", ACCENT)])
            } else {
                Line::from(part.name.clone())
            };
            vec![
                Cell::new(title),
                cell(nonempty(&part.state), partition_color(&part.state)),
                Cell::new(meter(
                    &partition_meter(part.used, part.idle, part.total),
                    11,
                )),
                Cell::new(quantity(part.total)),
                cell(quantity(part.idle), GREEN),
                cell(quantity(part.used), BLUE),
                cell(quantity(part.other), AMBER),
                quiet(nonempty(&part.limit)),
            ]
        }
        Record::Job(job) => {
            let context = if view == View::History {
                job.end
                    .map_or_else(|| "—".into(), |end| end.format("%m-%d %H:%M"))
            } else if job.state == JobState::Pending || job.hosts.is_empty() {
                nonempty(&job.reason)
            } else {
                job.hosts.clone()
            };
            let label = if job.state == JobState::Unknown {
                nonempty(&job.raw_state)
            } else {
                job.state.label().into()
            };
            vec![
                quiet(job.display_id().into()),
                cell(job.name.clone(), TEXT),
                cell(label, job_color(job.state)),
                Cell::new(nonempty(&job.partition)),
                quiet(duration(job.elapsed)),
                quiet(context),
            ]
        }
        Record::Node(node) => vec![
            Cell::new(node.name.clone()),
            cell(node.state.label().into(), node_color(node.state)),
            quiet(nonempty(&node.partitions.join(", "))),
            cell(format!("{}/{}", node.allocated_cpus, node.cpus), BLUE),
            quiet(memory(node.memory)),
            quiet(nonempty(&node.gpus.join(", "))),
        ],
    }
}

fn inspector(frame: &mut Frame<'_>, app: &mut App, area: Rect) {
    let side = area.width < 55;
    let hint = if side {
        " ↵ Details "
    } else {
        " Enter for full details "
    };
    let block = pane("Selection", false)
        .title(Line::from(muted(hint)).right_aligned())
        .padding(Padding::new(1, 1, 0, 0));
    let inside = block.inner(area);
    frame.render_widget(block, area);
    let Some(record) = app.pane().selected() else {
        frame.render_widget(Line::from(muted("Select a record to inspect it")), inside);
        return;
    };
    let (mut context, facts) = record_sections(record, false);
    if side {
        context.push(Line::default());
        context.extend(facts);
        frame.render_widget(Paragraph::new(context).wrap(Wrap { trim: false }), inside);
    } else {
        let [identity, information] =
            Layout::horizontal([Length((inside.width / 3).min(32)), Fill(1)]).areas(inside);
        frame.render_widget(Paragraph::new(context).wrap(Wrap { trim: true }), identity);
        frame.render_widget(
            Paragraph::new(facts).wrap(Wrap { trim: false }),
            information,
        );
    }
    app.hits.selection = area;
}

fn record_sections(record: Record<'_>, full: bool) -> (Vec<Line<'static>>, Vec<Line<'static>>) {
    let (kind, name, state, color, gauge) = match record {
        Record::Partition(part) => (
            "PARTITION".to_owned(),
            part.name.clone(),
            if part.default {
                format!("{}  ·  Default", nonempty(&part.state))
            } else {
                nonempty(&part.state)
            },
            partition_color(&part.state),
            Some(partition_meter(part.used, part.idle, part.total)),
        ),
        Record::Job(job) => (
            format!("JOB {}", job.display_id()),
            job.name.clone(),
            nonempty(&job.raw_state),
            job_color(job.state),
            None,
        ),
        Record::Node(node) => (
            "NODE".to_owned(),
            node.name.clone(),
            nonempty(&node.raw_state),
            node_color(node.state),
            Some([
                (node.allocated_cpus.min(node.cpus), BLUE),
                (node.cpus.saturating_sub(node.allocated_cpus), TEXT),
                (0, TEXT),
            ]),
        ),
    };
    let mut context = vec![
        Line::from(muted(kind)),
        Line::from(bold(name, TEXT)),
        Line::from(fg(format!("● {state}"), color)),
    ];
    if let Some(gauge) = gauge {
        context.push(Line::default());
        context.push(meter(&gauge, 18));
    }
    let mut facts = Vec::new();
    let mut field = |label: &str, value: String| {
        if !value.is_empty() {
            facts.push(Line::from(vec![
                muted(format!("{label:<12} ")),
                fg(value, TEXT),
            ]));
        }
    };
    match record {
        Record::Partition(part) => {
            field("Nodes", format!("{} total", quantity(part.total)));
            field("Allocated", quantity(part.used));
            field("Idle", quantity(part.idle));
            field("Other", quantity(part.other));
            field("Time limit", part.limit.clone());
            field("QoS", part.qos.clone());
            if full {
                field(
                    "Node range",
                    format!(
                        "{} – {}",
                        part.min_nodes.map_or_else(|| "—".into(), quantity),
                        part.max_nodes.map_or_else(|| "—".into(), quantity)
                    ),
                );
                field("Host names", part.hosts.clone());
            }
        }
        Record::Job(job) => {
            field("Partition", job.partition.clone());
            field("User", job.user.clone());
            field("Elapsed", duration(job.elapsed));
            field(
                "CPUs / GPUs",
                format!(
                    "{} / {}",
                    job.cpus,
                    job.gpus.map_or_else(|| "—".into(), quantity)
                ),
            );
            field("Memory", job.memory.map_or_else(String::new, memory));
            field("Node list", job.hosts.clone());
            field("Reason", job.reason.clone());
            if full {
                field("Job ID", job.id.clone());
                field("Nodes", quantity(job.nodes));
                field("Limit", job.limit.map_or_else(String::new, duration));
                for (label, stamp) in [
                    ("Submitted", job.submit),
                    ("Started", job.start),
                    ("Ended", job.end),
                ] {
                    field(
                        label,
                        stamp.map_or_else(String::new, |stamp: Stamp| {
                            stamp.format("%Y-%m-%d %H:%M:%S")
                        }),
                    );
                }
                field("Exit code", job.exit.clone());
                field(
                    "Peak memory",
                    job.peak_memory.map_or_else(String::new, memory),
                );
                field("CPU time", job.cpu_time.map_or_else(String::new, duration));
                field(
                    "Energy",
                    job.energy
                        .map_or_else(String::new, |value| format!("{} J", quantity(value))),
                );
            }
        }
        Record::Node(node) => {
            field(
                "CPUs used",
                format!("{} / {}", node.allocated_cpus, node.cpus),
            );
            field("Memory", memory(node.memory));
            field("Partitions", node.partitions.join(", "));
            field("GPUs", node.gpus.join(", "));
            field("Reason", node.reason.clone());
            if full {
                field(
                    "Memory used",
                    node.allocated_memory.map_or_else(String::new, memory),
                );
                field(
                    "Free memory",
                    node.free_memory.map_or_else(String::new, memory),
                );
                field("Features", node.features.join(", "));
            }
        }
    }
    (context, facts)
}

fn draw_overlay(frame: &mut Frame<'_>, overlay: &Overlay, area: Rect, hits: &mut Hits) {
    let (title, lines, scroll, height) = match overlay {
        Overlay::Menu(menu) => {
            draw_menu(frame, menu, area, hits);
            return;
        }
        Overlay::Detail(detail) => {
            let (mut lines, facts) = record_sections(detail.record(), true);
            lines.push(Line::default());
            lines.extend(facts);
            if let Some(message) = &detail.message {
                lines.push(Line::default());
                lines.push(Line::from(muted(message.clone())));
            }
            ("Record details", lines, detail.scroll, 25)
        }
        Overlay::Help => (
            "Keyboard shortcuts",
            [
                ("1–4 / Tab", "Switch views"),
                ("↑↓ / j k", "Select a row"),
                ("Enter", "Open details"),
                ("/ / f", "Filter by text or state"),
                ("Esc", "Clear filters or close this panel"),
                ("s", "Cycle default, name and state sort"),
                ("r / p", "Refresh now / pause polling"),
                ("c", "Choose configured cluster"),
                ("q", "Quit"),
            ]
            .into_iter()
            .map(|(key, description)| {
                Line::from(vec![
                    bold(format!("{key:<14}"), ACCENT),
                    fg(description, TEXT),
                ])
            })
            .collect(),
            0,
            16,
        ),
    };
    let window = centered(area, 76, height);
    frame.render_widget(Clear, window);
    let block = pane(title, true)
        .title_bottom(Line::from(muted(" Esc close ")).alignment(Alignment::Right))
        .padding(Padding::new(2, 2, 1, 1));
    let inside = block.inner(window);
    let rows: usize = lines
        .iter()
        .map(|line| {
            line.width()
                .max(1)
                .div_ceil(usize::from(inside.width.max(1)))
        })
        .sum();
    let limit = rows
        .saturating_sub(inside.height as usize)
        .min(u16::MAX as usize) as u16;
    frame.render_widget(
        Paragraph::new(lines)
            .block(block)
            .wrap(Wrap { trim: false })
            .scroll((scroll.min(limit), 0)),
        window,
    );
    hits.detail_scroll_limit = limit;
}

fn draw_menu(frame: &mut Frame<'_>, menu: &Menu, area: Rect, hits: &mut Hits) {
    let window = centered(area, 48, menu.choices.len().min(12) as u16 + 4);
    let block = pane(menu.title, true)
        .title_bottom(Line::from(muted(" ↑↓ move  ↵ apply  Esc close ")).right_aligned())
        .padding(Padding::new(2, 2, 1, 1));
    let inside = block.inner(window);
    frame.render_widget(Clear, window);
    frame.render_widget(block, window);
    let first = menu
        .cursor
        .saturating_sub(usize::from(inside.height.saturating_sub(1)));
    let rows = menu
        .choices
        .iter()
        .enumerate()
        .skip(first)
        .take(usize::from(inside.height));
    for (index, choice) in rows {
        let row = Rect::new(inside.x, inside.y + (index - first) as u16, inside.width, 1);
        let [label, hint] = Layout::horizontal([Fill(1), Length(8)]).areas(row);
        let line = if index == menu.cursor {
            Line::from(vec![bold("› ", ACCENT), bold(choice.label.as_str(), TEXT)])
        } else {
            Line::from(vec![Span::raw("  "), fg(choice.label.as_str(), TEXT)])
        };
        frame.render_widget(line, label);
        frame.render_widget(
            Line::from(muted(choice.hint.as_str())).right_aligned(),
            hint,
        );
    }
    let visible = (menu.choices.len() - first).min(usize::from(inside.height));
    hits.menu = Some((
        Rect::new(inside.x, inside.y, inside.width, visible as u16),
        first,
    ));
}

fn centered(area: Rect, width: u16, height: u16) -> Rect {
    let width = area.width.saturating_sub(4).min(width);
    let height = area.height.saturating_sub(4).min(height);
    Rect::new(
        area.x + (area.width - width) / 2,
        area.y + (area.height - height) / 2,
        width,
        height,
    )
}

fn status_bar(frame: &mut Frame<'_>, app: &App, area: Rect) {
    let pane = app.pane();
    let (state, color) = if pane.error.is_some() && pane.data.is_none() {
        ("Unavailable", RED)
    } else if pane.error.is_some() {
        ("Stale", AMBER)
    } else if pane.task.is_some() {
        ("Refreshing", BLUE)
    } else if pane.data.is_some() {
        ("Updated", GREEN)
    } else {
        ("Waiting", TEXT)
    };
    let mut line = vec![bold(format!("  ● {state}"), color)];
    if let Some(updated) = pane.updated {
        line.push(muted(format!(" {}", updated.format("%H:%M:%S"))));
    }
    if let Some(error) = &pane.error {
        line.push(fg(format!("  ·  {error}"), color));
    } else if app.paused {
        line.push(fg("  ·  Polling paused", AMBER));
    } else {
        line.push(muted(format!("  ·  Every {}s", app.interval().as_secs())));
    }
    if let Some(index) = pane.table.selected()
        && area.width >= 60
        && pane.error.is_none()
    {
        let [refresh, selection] = Layout::horizontal([Fill(1), Length(19)]).areas(area);
        let label = format!(
            "Row {} / {} ",
            quantity(index as u64 + 1),
            quantity(pane.matches.len() as u64)
        );
        frame.render_widget(Line::from(line), refresh);
        frame.render_widget(Line::from(muted(label)).right_aligned(), selection);
    } else {
        frame.render_widget(Line::from(line), area);
    }
}

fn shortcuts(frame: &mut Frame<'_>, app: &App, area: Rect) {
    let shortcuts: &[(&str, &str)] = if app.editing {
        &[("Enter", "Apply"), ("Esc", "Clear"), ("Ctrl+U", "Reset")]
    } else if area.width < 48 {
        &[
            ("/", "Filter"),
            ("f", "State"),
            ("↵", "Details"),
            ("?", "Help"),
        ]
    } else if area.width < 75 {
        &[
            ("/", "Filter"),
            ("f", "State"),
            ("↵", "Details"),
            ("r", "Refresh"),
            ("?", "Help"),
            ("q", "Quit"),
        ]
    } else {
        &[
            ("/", "Filter"),
            ("f", "State"),
            ("↵", "Details"),
            ("s", "Sort"),
            ("r", "Refresh"),
            ("p", "Pause"),
            ("?", "Help"),
            ("q", "Quit"),
        ]
    };
    let mut line = Vec::new();
    for (key, label) in shortcuts {
        line.push(bold(format!("  {key}"), ACCENT));
        line.push(fg(format!(" {label}"), TEXT));
    }
    frame.render_widget(Line::from(line), area);
}

fn inset(area: Rect, horizontal: u16, vertical: u16) -> Rect {
    Rect::new(
        area.x + horizontal.min(area.width),
        area.y + vertical.min(area.height),
        area.width.saturating_sub(horizontal * 2),
        area.height.saturating_sub(vertical * 2),
    )
}

fn partition_meter(used: u64, idle: u64, total: u64) -> [(u64, Color); 3] {
    let used = used.min(total);
    let idle = idle.min(total - used);
    [(used, BLUE), (idle, GREEN), (total - used - idle, AMBER)]
}

fn meter(buckets: &[(u64, Color)], width: u16) -> Line<'static> {
    let total: u128 = buckets.iter().map(|&(number, _)| u128::from(number)).sum();
    if total == 0 {
        return Line::from(muted("━".repeat(width as usize)));
    }
    let mut cumulative = 0_u128;
    let mut end = 0;
    let mut spans = Vec::new();
    for &(number, color) in buckets {
        cumulative += u128::from(number);
        let next = ((cumulative * u128::from(width) + total / 2) / total) as usize;
        let bar = "━".repeat(next - end);
        spans.push(if color == TEXT {
            muted(bar)
        } else {
            fg(bar, color)
        });
        end = next;
    }
    Line::from(spans)
}

fn partition_color(state: &str) -> Color {
    if state
        .to_ascii_uppercase()
        .split(['+', ' '])
        .any(|s| matches!(s, "UP" | "ACTIVE" | "AVAILABLE"))
    {
        GREEN
    } else {
        AMBER
    }
}
fn job_color(state: JobState) -> Color {
    match state {
        JobState::Running | JobState::Completed => GREEN,
        JobState::Pending | JobState::Cancelled => AMBER,
        JobState::Failed | JobState::OutOfMemory | JobState::Timeout => RED,
        JobState::Suspended => MAGENTA,
        JobState::Unknown => TEXT,
    }
}
fn node_color(state: NodeState) -> Color {
    match state {
        NodeState::Idle => GREEN,
        NodeState::Allocated | NodeState::Completing => BLUE,
        NodeState::Mixed => MAGENTA,
        NodeState::Drained => AMBER,
        NodeState::Down => RED,
        NodeState::Unknown => TEXT,
    }
}

fn nonempty(s: &str) -> String {
    if s.is_empty() { "—".into() } else { s.into() }
}
fn fg<'a>(s: impl Into<std::borrow::Cow<'a, str>>, color: Color) -> Span<'a> {
    Span::styled(s, Style::new().fg(color))
}
fn bold<'a>(s: impl Into<std::borrow::Cow<'a, str>>, color: Color) -> Span<'a> {
    Span::styled(s, Style::new().fg(color).add_modifier(Modifier::BOLD))
}

fn muted<'a>(s: impl Into<std::borrow::Cow<'a, str>>) -> Span<'a> {
    Span::styled(s, DIM)
}
