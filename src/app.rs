use std::{collections::BTreeMap, sync::Arc, time::Instant};

use anyhow::Result;
use chrono::{DateTime, Local};
use crossterm::{
    event::{
        DisableBracketedPaste, DisableMouseCapture, EnableBracketedPaste, EnableMouseCapture,
        Event, EventStream, KeyCode, KeyEvent, KeyEventKind, KeyModifiers, MouseButton, MouseEvent,
        MouseEventKind,
    },
    execute,
};
use futures_util::StreamExt;
use ratatui::{
    layout::{Position, Rect},
    widgets::TableState,
};
use tokio::{sync::mpsc, task::JoinHandle};

use crate::{
    config::{Config, Refresh},
    model::{Data, Job, Node, Partition, Snapshot, View, quantity, safe},
    slurm::{Source, interval},
    ui,
};

#[derive(Clone, Copy)]
pub enum Record<'a> {
    Partition(&'a Partition),
    Job(&'a Job),
    Node(&'a Node),
}

impl Record<'_> {
    fn key(self) -> String {
        match self {
            Self::Job(job) => format!("{}:{:?}", job.id, job.submit),
            Self::Partition(partition) => partition.name.clone(),
            Self::Node(node) => node.name.clone(),
        }
    }

    fn name(self) -> String {
        match self {
            Self::Job(job) => job.name.to_lowercase(),
            Self::Partition(partition) => partition.name.to_lowercase(),
            Self::Node(node) => node.name.to_lowercase(),
        }
    }

    fn state(self) -> String {
        match self {
            Self::Job(job) => job.state.label().into(),
            Self::Partition(partition) if partition.state.is_empty() => "Unknown".into(),
            Self::Partition(partition) => partition.state.clone(),
            Self::Node(node) => node.state.label().into(),
        }
    }

    fn search(self) -> String {
        match self {
            Self::Job(job) => format!(
                "{} {} {} {} {} {} {} {} {}",
                job.id,
                job.display_id(),
                job.name,
                job.partition,
                job.user,
                job.state.label(),
                job.raw_state,
                job.reason,
                job.hosts
            ),
            Self::Partition(part) => {
                format!("{} {} {} {}", part.name, part.state, part.qos, part.hosts)
            }
            Self::Node(node) => format!(
                "{} {} {} {} {} {} {}",
                node.name,
                node.state.label(),
                node.raw_state,
                node.partitions.join(" "),
                node.gpus.join(" "),
                node.features.join(" "),
                node.reason
            ),
        }
        .to_lowercase()
    }
}

enum DetailRecord {
    Partition(Partition),
    Job(Box<Job>),
    Node(Node),
}
impl From<Record<'_>> for DetailRecord {
    fn from(value: Record<'_>) -> Self {
        match value {
            Record::Partition(part) => Self::Partition(part.clone()),
            Record::Job(job) => Self::Job(Box::new(job.clone())),
            Record::Node(node) => Self::Node(node.clone()),
        }
    }
}

pub struct Detail {
    record: DetailRecord,
    pub message: Option<String>,
    pub scroll: u16,
    request: u64,
}
impl Detail {
    pub fn record(&self) -> Record<'_> {
        match &self.record {
            DetailRecord::Partition(part) => Record::Partition(part),
            DetailRecord::Job(job) => Record::Job(job),
            DetailRecord::Node(node) => Record::Node(node),
        }
    }
}

pub enum Overlay {
    Help,
    Menu(Menu),
    Detail(Box<Detail>),
}

pub struct Menu {
    pub title: &'static str,
    pub choices: Vec<Choice>,
    pub cursor: usize,
}

pub struct Choice {
    pub label: String,
    pub hint: String,
    action: MenuAction,
}

#[derive(Clone)]
enum MenuAction {
    Cluster(usize),
    State(Option<String>),
}

impl Menu {
    fn move_by(&mut self, amount: isize) {
        self.cursor = self
            .cursor
            .saturating_add_signed(amount)
            .min(self.choices.len() - 1);
    }
}

enum Update {
    Snapshot(View, Result<Snapshot>),
    Accounting(u64, Box<Result<Job>>),
}

#[derive(Clone, Copy, Default)]
pub enum Sort {
    #[default]
    Default,
    Name,
    State,
}

impl Sort {
    pub fn label(self) -> &'static str {
        match self {
            Self::Default => "Default",
            Self::Name => "Name",
            Self::State => "State",
        }
    }

    fn next(self) -> Self {
        match self {
            Self::Default => Self::Name,
            Self::Name => Self::State,
            Self::State => Self::Default,
        }
    }
}

#[derive(Default)]
pub struct Pane {
    pub data: Option<Data>,
    pub matches: Vec<usize>,
    pub filter: String,
    pub state_filter: Option<String>,
    pub sort: Sort,
    pub table: TableState,
    pub updated: Option<DateTime<Local>>,
    pub error: Option<String>,
    pub task: Option<JoinHandle<()>>,
    attempt: Option<Instant>,
}

impl Pane {
    pub fn len(&self) -> usize {
        match &self.data {
            Some(Data::Overview { partitions, .. }) => partitions.len(),
            Some(Data::Jobs(jobs)) => jobs.len(),
            Some(Data::Nodes(nodes)) => nodes.len(),
            None => 0,
        }
    }

    pub fn row(&self, index: usize) -> Option<Record<'_>> {
        match self.data.as_ref()? {
            Data::Overview { partitions, .. } => partitions.get(index).map(Record::Partition),
            Data::Jobs(jobs) => jobs.get(index).map(Record::Job),
            Data::Nodes(nodes) => nodes.get(index).map(Record::Node),
        }
    }

    pub fn selected(&self) -> Option<Record<'_>> {
        self.row(*self.matches.get(self.table.selected()?)?)
    }

    pub fn is_filtered(&self) -> bool {
        self.state_filter.is_some() || !self.filter.trim().is_empty()
    }

    fn update_rows(&mut self, keep: Option<String>) {
        let pattern = self.filter.to_lowercase();
        let tokens: Vec<_> = pattern.split_whitespace().collect();
        let previous = self.table.selected().unwrap_or(0);
        let mut matching: Vec<_> = (0..self.len())
            .filter(|&index| {
                let record = self.row(index).expect("row in bounds");
                if self
                    .state_filter
                    .as_ref()
                    .is_some_and(|state| record.state() != *state)
                {
                    return false;
                }
                if tokens.is_empty() {
                    return true;
                }
                let haystack = record.search();
                tokens.iter().all(|word| haystack.contains(word))
            })
            .collect();
        match self.sort {
            Sort::Name => {
                matching.sort_by_cached_key(|&index| self.row(index).expect("row in bounds").name())
            }
            Sort::State => matching
                .sort_by_cached_key(|&index| self.row(index).expect("row in bounds").state()),
            Sort::Default => {}
        }
        let index = keep.and_then(|key| {
            matching
                .iter()
                .position(|&index| self.row(index).is_some_and(|record| record.key() == key))
        });
        self.matches = matching;
        if self.matches.is_empty() {
            self.table.select(None);
        } else {
            self.table.select(Some(
                index.unwrap_or_else(|| previous.min(self.matches.len() - 1)),
            ));
        }
    }

    fn move_by(&mut self, amount: isize) {
        if !self.matches.is_empty() {
            let index = self.table.selected().unwrap_or(0);
            self.table.select(Some(
                index
                    .saturating_add_signed(amount)
                    .min(self.matches.len() - 1),
            ));
        }
    }
}

#[derive(Default)]
pub struct Hits {
    pub tabs: [Rect; 4],
    pub body: Rect,
    pub filter: Rect,
    pub state_filter: Rect,
    pub sort: Rect,
    pub cluster: Rect,
    pub menu: Option<(Rect, usize)>,
    pub selection: Rect,
    pub heatmap: Vec<(Rect, usize)>,
    pub detail_scroll_limit: u16,
}

pub struct App {
    pub sources: Vec<Arc<Source>>,
    pub cluster: usize,
    pub version: String,
    pub view: View,
    pub editing: bool,
    pub overlay: Option<Overlay>,
    pub paused: bool,
    pub hits: Hits,
    panes: [Pane; 4],
    refresh: Refresh,
    updates: mpsc::UnboundedSender<(u64, Update)>,
    generation: u64,
    detail_sequence: u64,
    detail_task: Option<JoinHandle<()>>,
}

impl App {
    fn new(config: Config, selected: usize, updates: mpsc::UnboundedSender<(u64, Update)>) -> Self {
        Self {
            sources: config
                .clusters
                .into_iter()
                .map(|cluster| Arc::new(Source::new(cluster)))
                .collect(),
            cluster: selected,
            view: View::Overview,
            version: String::new(),
            editing: false,
            overlay: None,
            paused: false,
            hits: Hits::default(),
            panes: std::array::from_fn(|_| Pane::default()),
            refresh: config.application.refresh,
            updates,
            generation: 0,
            detail_sequence: 0,
            detail_task: None,
        }
    }

    pub fn pane(&self) -> &Pane {
        &self.panes[self.view.index()]
    }
    pub fn pane_mut(&mut self) -> &mut Pane {
        &mut self.panes[self.view.index()]
    }
    pub fn interval(&self) -> std::time::Duration {
        interval(&self.refresh, self.view)
    }

    fn poll(&mut self, force: bool) -> bool {
        let view = self.view;
        let interval = self.interval();
        let should_poll = {
            let pane = self.pane();
            pane.task.is_none()
                && (force
                    || pane
                        .attempt
                        .is_none_or(|time| !self.paused && time.elapsed() >= interval))
        };
        if !should_poll {
            return false;
        }
        let source = Arc::clone(&self.sources[self.cluster]);
        let sender = self.updates.clone();
        let generation = self.generation;
        let pane = self.pane_mut();
        pane.attempt = Some(Instant::now());
        pane.task = Some(tokio::spawn(async move {
            let result = source.snapshot(view).await;
            let _ = sender.send((generation, Update::Snapshot(view, result)));
        }));
        true
    }

    fn receive(&mut self, generation: u64, update: Update) {
        if generation != self.generation {
            return;
        }
        match update {
            Update::Snapshot(view, result) => {
                let pane = &mut self.panes[view.index()];
                pane.task = None;
                match result {
                    Ok(snapshot) => {
                        let keep = pane.selected().map(Record::key);
                        self.version = snapshot.version;
                        pane.data = Some(snapshot.data);
                        pane.error = None;
                        pane.updated = Some(Local::now());
                        pane.update_rows(keep);
                    }
                    Err(error) => pane.error = Some(safe(&error.to_string())),
                }
            }
            Update::Accounting(sequence, result) => {
                if let Some(Overlay::Detail(detail)) = &mut self.overlay
                    && detail.request == sequence
                {
                    self.detail_task = None;
                    match *result {
                        Ok(job) => {
                            detail.record = DetailRecord::Job(Box::new(job));
                            detail.message = None;
                        }
                        Err(_) => {
                            detail.message = Some("More accounting data is unavailable.".into())
                        }
                    }
                }
            }
        }
    }

    fn switch(&mut self, view: View) {
        self.view = view;
        self.editing = false;
        self.poll(false);
    }

    fn switch_cluster(&mut self, cluster: usize) {
        self.overlay = None;
        if cluster == self.cluster {
            return;
        }
        self.cluster = cluster;
        self.version.clear();
        self.generation += 1;
        self.cancel_workers();
        self.panes = std::array::from_fn(|_| Pane::default());
        self.poll(false);
    }

    fn cancel_workers(&mut self) {
        for pane in &mut self.panes {
            if let Some(task) = pane.task.take() {
                task.abort();
            }
        }
        if let Some(task) = self.detail_task.take() {
            task.abort();
        }
    }

    fn open_detail(&mut self) {
        let Some(record) = self.pane().selected().map(DetailRecord::from) else {
            return;
        };
        self.detail_sequence += 1;
        let request = self.detail_sequence;
        let mut detail = Detail {
            record,
            message: None,
            scroll: 0,
            request,
        };
        let source = Arc::clone(&self.sources[self.cluster]);
        if self.view == View::History
            && source.cluster.backend == crate::config::Backend::Ssh
            && let DetailRecord::Job(job) = &detail.record
        {
            detail.message = Some("Loading accounting…".into());
            let (sender, generation, job) = (self.updates.clone(), self.generation, job.clone());
            self.detail_task = Some(tokio::spawn(async move {
                let update = Update::Accounting(request, Box::new(source.accounting(&job).await));
                let _ = sender.send((generation, update));
            }));
        }
        self.overlay = Some(Overlay::Detail(Box::new(detail)));
    }

    fn close_overlay(&mut self) {
        self.overlay = None;
        if let Some(task) = self.detail_task.take() {
            task.abort();
        }
    }

    fn pick_cluster(&mut self) {
        if self.sources.len() > 1 {
            self.editing = false;
            self.overlay = Some(Overlay::Menu(Menu {
                title: "Choose cluster",
                choices: self
                    .sources
                    .iter()
                    .enumerate()
                    .map(|(index, source)| Choice {
                        label: source.cluster.name.clone(),
                        hint: match source.cluster.backend {
                            crate::config::Backend::Mock => "demo",
                            crate::config::Backend::Ssh => "ssh",
                        }
                        .into(),
                        action: MenuAction::Cluster(index),
                    })
                    .collect(),
                cursor: self.cluster,
            }));
        }
    }

    fn pick_state(&mut self) {
        let pane = self.pane();
        let mut counts = BTreeMap::new();
        for state in (0..pane.len()).filter_map(|index| pane.row(index).map(Record::state)) {
            *counts.entry(state).or_insert(0) += 1;
        }
        if let Some(selected) = &pane.state_filter {
            counts.entry(selected.clone()).or_default();
        }
        let cursor = pane
            .state_filter
            .as_ref()
            .and_then(|selected| {
                counts
                    .keys()
                    .position(|state| state == selected)
                    .map(|index| index + 1)
            })
            .unwrap_or(0);
        let all = Choice {
            label: "All states".into(),
            hint: quantity(pane.len() as u64),
            action: MenuAction::State(None),
        };
        let choices = std::iter::once(all)
            .chain(counts.into_iter().map(|(state, count)| Choice {
                label: state.clone(),
                hint: quantity(count),
                action: MenuAction::State(Some(state)),
            }))
            .collect();
        self.editing = false;
        self.overlay = Some(Overlay::Menu(Menu {
            title: "Filter by state",
            choices,
            cursor,
        }));
    }

    fn choose(&mut self, action: MenuAction) {
        self.overlay = None;
        match action {
            MenuAction::Cluster(cluster) => self.switch_cluster(cluster),
            MenuAction::State(state) => {
                let pane = self.pane_mut();
                let keep = pane.selected().map(Record::key);
                pane.state_filter = state;
                pane.update_rows(keep);
            }
        }
    }

    fn change_sort(&mut self) {
        let pane = self.pane_mut();
        let keep = pane.selected().map(Record::key);
        pane.sort = pane.sort.next();
        pane.update_rows(keep);
    }

    fn paste(&mut self, input: &str) {
        if !self.editing {
            return;
        }
        let pane = self.pane_mut();
        let remaining = 160_usize.saturating_sub(pane.filter.chars().count());
        pane.filter
            .extend(input.chars().filter(|ch| !ch.is_control()).take(remaining));
        pane.update_rows(pane.selected().map(Record::key));
    }

    fn on_key(&mut self, key: KeyEvent) -> bool {
        if key.kind == KeyEventKind::Release {
            return false;
        }
        if key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL) {
            return true;
        }
        if let Some(overlay) = &mut self.overlay {
            match (overlay, key.code) {
                (_, KeyCode::Esc | KeyCode::Char('q')) => self.close_overlay(),
                (Overlay::Menu(menu), KeyCode::Down | KeyCode::Char('j')) => {
                    menu.move_by(1);
                }
                (Overlay::Menu(menu), KeyCode::Up | KeyCode::Char('k')) => {
                    menu.move_by(-1);
                }
                (Overlay::Menu(menu), KeyCode::Home) => menu.move_by(isize::MIN),
                (Overlay::Menu(menu), KeyCode::End) => menu.move_by(isize::MAX),
                (Overlay::Menu(menu), KeyCode::Enter) => {
                    let action = menu.choices[menu.cursor].action.clone();
                    self.choose(action);
                }
                (Overlay::Detail(detail), code) => {
                    let change = match code {
                        KeyCode::Up | KeyCode::Char('k') => -1,
                        KeyCode::Down | KeyCode::Char('j') => 1,
                        KeyCode::PageUp => -8,
                        KeyCode::PageDown => 8,
                        _ => 0,
                    };
                    detail.scroll = detail
                        .scroll
                        .saturating_add_signed(change)
                        .min(self.hits.detail_scroll_limit);
                }
                _ => {}
            }
            return false;
        }
        if self.editing {
            match key.code {
                KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                    self.clear_text()
                }
                KeyCode::Char(c) if !key.modifiers.contains(KeyModifiers::CONTROL) => {
                    self.paste(&c.to_string())
                }
                KeyCode::Backspace => {
                    let pane = self.pane_mut();
                    pane.filter.pop();
                    pane.update_rows(pane.selected().map(Record::key));
                }
                KeyCode::Enter => self.editing = false,
                KeyCode::Esc => {
                    self.editing = false;
                    self.clear_text();
                }
                _ => {}
            }
            return false;
        }
        let page = self.hits.body.height.saturating_sub(2).max(1) as isize;
        match key.code {
            KeyCode::Char('q') => return true,
            KeyCode::Char(c @ '1'..='4') => self.switch(View::ALL[c as usize - '1' as usize]),
            KeyCode::Tab | KeyCode::Right => self.switch(self.view.next(false)),
            KeyCode::BackTab | KeyCode::Left => self.switch(self.view.next(true)),
            KeyCode::Up | KeyCode::Char('k') => self.pane_mut().move_by(-1),
            KeyCode::Down | KeyCode::Char('j') => self.pane_mut().move_by(1),
            KeyCode::PageUp => self.pane_mut().move_by(-page),
            KeyCode::PageDown => self.pane_mut().move_by(page),
            KeyCode::Home => self.pane_mut().move_by(isize::MIN),
            KeyCode::End => self.pane_mut().move_by(isize::MAX),
            KeyCode::Char('/') => self.editing = true,
            KeyCode::Esc => {
                self.pane_mut().state_filter = None;
                self.clear_text();
            }
            KeyCode::Enter => self.open_detail(),
            KeyCode::Char('f') => self.pick_state(),
            KeyCode::Char('s') => self.change_sort(),
            KeyCode::Char('r') => {
                self.poll(true);
            }
            KeyCode::Char('p') => {
                self.paused = !self.paused;
                self.poll(false);
            }
            KeyCode::Char('c') => self.pick_cluster(),
            KeyCode::Char('?') => self.overlay = Some(Overlay::Help),
            _ => {}
        }
        false
    }

    fn clear_text(&mut self) {
        let pane = self.pane_mut();
        pane.filter.clear();
        pane.update_rows(pane.selected().map(Record::key));
    }

    fn on_mouse(&mut self, mouse: MouseEvent) {
        let pos = Position::new(mouse.column, mouse.row);
        if let Some(overlay) = &mut self.overlay {
            match overlay {
                Overlay::Detail(detail) => match mouse.kind {
                    MouseEventKind::ScrollUp => detail.scroll = detail.scroll.saturating_sub(3),
                    MouseEventKind::ScrollDown => {
                        detail.scroll = detail
                            .scroll
                            .saturating_add(3)
                            .min(self.hits.detail_scroll_limit)
                    }
                    _ => {}
                },
                Overlay::Menu(menu) => {
                    if let Some((rows, offset)) = self.hits.menu
                        && rows.contains(pos)
                    {
                        match mouse.kind {
                            MouseEventKind::ScrollUp => menu.move_by(-1),
                            MouseEventKind::ScrollDown => menu.move_by(1),
                            MouseEventKind::Down(MouseButton::Left) => {
                                let index = offset + usize::from(pos.y - rows.y);
                                let action = menu.choices[index].action.clone();
                                self.choose(action);
                            }
                            _ => {}
                        }
                    }
                }
                Overlay::Help => {}
            }
            return;
        }
        let heatmap_row = self
            .hits
            .heatmap
            .iter()
            .find(|(tile, _)| tile.contains(pos))
            .map(|(_, index)| *index);
        let over_records = self.hits.body.contains(pos) || heatmap_row.is_some();
        match mouse.kind {
            MouseEventKind::ScrollUp if over_records => self.pane_mut().move_by(-3),
            MouseEventKind::ScrollDown if over_records => self.pane_mut().move_by(3),
            MouseEventKind::Down(MouseButton::Left) => {
                if let Some(index) = self.hits.tabs.iter().position(|tab| tab.contains(pos)) {
                    self.switch(View::ALL[index]);
                } else if self.hits.filter.contains(pos) {
                    self.editing = true;
                } else if self.hits.state_filter.contains(pos) {
                    self.pick_state();
                } else if self.hits.sort.contains(pos) {
                    self.editing = false;
                    self.change_sort();
                } else if self.hits.cluster.contains(pos) {
                    self.pick_cluster();
                } else if self.hits.selection.contains(pos) {
                    self.editing = false;
                    self.open_detail();
                } else if let Some(index) = heatmap_row {
                    self.editing = false;
                    self.pane_mut().table.select(Some(index));
                } else if self.hits.body.contains(pos) {
                    self.editing = false;
                    let relative_row = (pos.y - self.hits.body.y) as usize;
                    let pane = self.pane_mut();
                    let index = pane.table.offset() + relative_row;
                    if index < pane.matches.len() {
                        pane.table.select(Some(index));
                    }
                }
            }
            _ => {}
        }
    }
}

pub async fn run(config: Config, selected: usize) -> Result<()> {
    let mut terminal = ratatui::try_init()?;
    let restore = RestoreTerminal;
    execute!(std::io::stdout(), EnableMouseCapture, EnableBracketedPaste)?;

    let (sender, mut receiver) = mpsc::unbounded_channel();
    let mut app = App::new(config, selected, sender);
    let mut events = EventStream::new();
    let mut tick = tokio::time::interval(std::time::Duration::from_millis(500));
    app.poll(false);
    let mut redraw = true;
    let result = loop {
        if redraw && let Err(error) = terminal.draw(|frame| ui::draw(frame, &mut app)) {
            break Err(error.into());
        }
        redraw = tokio::select! {
            event = events.next() => match event {
                Some(Ok(Event::Key(key))) => {
                    if app.on_key(key) { break Ok(()); }
                    key.kind != KeyEventKind::Release
                }
                Some(Ok(Event::Mouse(mouse))) if matches!(mouse.kind, MouseEventKind::Moved | MouseEventKind::Drag(_)) => false,
                Some(Ok(Event::Mouse(mouse))) => { app.on_mouse(mouse); true }
                Some(Ok(Event::Paste(input))) => { app.paste(&input); true }
                Some(Ok(Event::Resize(..))) => true,
                Some(Ok(_)) => false,
                Some(Err(error)) => break Err(error.into()),
                None => break Ok(()),
            },
            Some((generation, update)) = receiver.recv() => { app.receive(generation, update); true }
            _ = tick.tick() => app.poll(false),
        };
    };
    app.cancel_workers();
    drop(restore);
    result
}

struct RestoreTerminal;
impl Drop for RestoreTerminal {
    fn drop(&mut self) {
        let _ = execute!(
            std::io::stdout(),
            DisableBracketedPaste,
            DisableMouseCapture
        );
        ratatui::restore();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::{Terminal, backend::TestBackend, style::Color};

    #[tokio::test]
    async fn filtering_and_selection_survive_a_snapshot_update() {
        let (sender, _receiver) = mpsc::unbounded_channel();
        let mut app = App::new(crate::config::load(None, true).unwrap(), 0, sender);
        app.view = View::Queue;
        let snapshot = app.sources[0].snapshot(View::Queue).await.unwrap();
        app.receive(0, Update::Snapshot(View::Queue, Ok(snapshot)));
        assert_eq!(app.pane().len(), 11);
        app.on_key(KeyEvent::new(KeyCode::Char('/'), KeyModifiers::NONE));
        app.paste("gpu");
        app.on_key(KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE));
        assert_eq!(app.pane().matches.len(), 2);
        app.pane_mut().move_by(1);
        let selected = app.pane().selected().unwrap().key();
        app.receive(
            0,
            Update::Snapshot(View::Queue, Err(anyhow::anyhow!("Temporary failure"))),
        );
        assert_eq!(app.pane().selected().unwrap().key(), selected);
        assert_eq!(app.pane().error.as_deref(), Some("Temporary failure"));
        let snapshot = app.sources[0].snapshot(View::Queue).await.unwrap();
        app.receive(0, Update::Snapshot(View::Queue, Ok(snapshot)));
        assert_eq!(app.pane().selected().unwrap().key(), selected);
        assert!(app.pane().error.is_none());
    }

    #[tokio::test]
    async fn renders_responsive_view_and_detail_overlay() {
        let (sender, _receiver) = mpsc::unbounded_channel();
        let mut app = App::new(crate::config::load(None, true).unwrap(), 0, sender);
        let snapshot = app.sources[0].snapshot(View::Overview).await.unwrap();
        app.receive(0, Update::Snapshot(View::Overview, Ok(snapshot)));
        for (width, height) in [(132, 32), (80, 24), (46, 14)] {
            let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
            terminal.draw(|frame| ui::draw(frame, &mut app)).unwrap();
            let screen = terminal.backend().to_string();
            assert!(screen.contains(if width < 49 { "Cluster" } else { "Overview" }));
            assert!(screen.contains("Views") && screen.contains("Partitions"));
            assert!(screen.matches('╭').count() >= 2);
            assert_eq!(screen.contains("Selection"), width == 132);
            assert_eq!(screen.contains("Partition heatmap"), width >= 80);
            assert!(screen.contains("compute"));
            assert_terminal_colors(terminal.backend());
            app.on_key(KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE));
            terminal.draw(|frame| ui::draw(frame, &mut app)).unwrap();
            assert!(terminal.backend().to_string().contains("Record details"));
            assert_terminal_colors(terminal.backend());
            app.on_key(KeyEvent::new(KeyCode::Esc, KeyModifiers::NONE));
        }
    }

    #[tokio::test]
    async fn heatmap_brings_selection_into_view_and_clicks_select_the_table_row() {
        let (sender, _receiver) = mpsc::unbounded_channel();
        let mut app = App::new(crate::config::load(None, true).unwrap(), 0, sender);
        let snapshot = app.sources[0].snapshot(View::Overview).await.unwrap();
        app.receive(0, Update::Snapshot(View::Overview, Ok(snapshot)));
        let mut terminal = Terminal::new(TestBackend::new(80, 24)).unwrap();
        app.on_key(KeyEvent::new(KeyCode::End, KeyModifiers::NONE));
        terminal.draw(|frame| ui::draw(frame, &mut app)).unwrap();
        assert!(
            app.hits
                .heatmap
                .iter()
                .any(|(_, index)| Some(*index) == app.pane().table.selected())
        );
        let (card, index) = app.hits.heatmap[0];
        app.on_mouse(MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column: card.x + 1,
            row: card.y,
            modifiers: KeyModifiers::NONE,
        });
        assert_eq!(app.pane().table.selected(), Some(index));
        app.on_key(KeyEvent::new(KeyCode::Char('/'), KeyModifiers::NONE));
        app.paste("compute");
        terminal.draw(|frame| ui::draw(frame, &mut app)).unwrap();
        assert_eq!(app.pane().matches.len(), 1);
        assert_eq!(app.hits.heatmap.len(), 1);
    }

    #[tokio::test]
    async fn heatmap_cards_align_for_partitions_with_different_node_counts() {
        let (sender, _receiver) = mpsc::unbounded_channel();
        let mut app = App::new(crate::config::load(None, true).unwrap(), 0, sender);
        let mut snapshot = app.sources[0].snapshot(View::Overview).await.unwrap();
        let Data::Overview { partitions, .. } = &mut snapshot.data else {
            panic!("Expected partitions");
        };
        partitions[0].total = 754;
        partitions[0].used = 44;
        partitions[0].idle = 31;
        partitions[0].other = 679;
        partitions[1].total = 2;
        partitions[1].used = 1;
        partitions[1].idle = 1;
        partitions[1].other = 0;
        app.receive(0, Update::Snapshot(View::Overview, Ok(snapshot)));

        let mut terminal = Terminal::new(TestBackend::new(132, 65)).unwrap();
        terminal.draw(|frame| ui::draw(frame, &mut app)).unwrap();
        let screen = terminal.backend().to_string();
        assert!(screen.contains("Share of each partition"));
        assert!(screen.contains("90%") && screen.contains("50%"));
        let cards = &app.hits.heatmap;
        assert_eq!(cards.len(), app.pane().matches.len());
        assert_eq!(cards[0].0.y, cards[1].0.y);
        assert_eq!(cards[0].0.height, cards[1].0.height);
        assert_eq!(cards[2].0.y - cards[0].0.y, cards[0].0.height + 1);
        assert_terminal_colors(terminal.backend());
    }

    #[tokio::test]
    async fn state_picker_combines_with_search_and_restores_the_full_queue() {
        let (sender, _receiver) = mpsc::unbounded_channel();
        let mut app = App::new(crate::config::load(None, true).unwrap(), 0, sender);
        app.view = View::Queue;
        let snapshot = app.sources[0].snapshot(View::Queue).await.unwrap();
        app.receive(0, Update::Snapshot(View::Queue, Ok(snapshot)));
        let key = |code| KeyEvent::new(code, KeyModifiers::NONE);

        app.on_key(key(KeyCode::Char('f')));
        app.on_key(key(KeyCode::Down));
        app.on_key(key(KeyCode::Enter));
        assert_eq!(app.pane().state_filter.as_deref(), Some("Pending"));
        assert_eq!(app.pane().matches.len(), 2);

        app.on_key(key(KeyCode::Char('/')));
        app.paste("preprocess");
        app.on_key(key(KeyCode::Enter));
        assert_eq!(app.pane().matches.len(), 1);
        let selected = app.pane().selected().unwrap().key();
        app.on_key(key(KeyCode::Esc));
        assert_eq!(app.pane().matches.len(), 11);
        assert_eq!(app.pane().selected().unwrap().key(), selected);

        let mut terminal = Terminal::new(TestBackend::new(132, 32)).unwrap();
        terminal.draw(|frame| ui::draw(frame, &mut app)).unwrap();
        let state = app.hits.state_filter;
        let click = |column, row| MouseEvent {
            kind: MouseEventKind::Down(MouseButton::Left),
            column,
            row,
            modifiers: KeyModifiers::NONE,
        };
        app.on_mouse(click(state.x, state.y));
        terminal.draw(|frame| ui::draw(frame, &mut app)).unwrap();
        let (menu, first) = app.hits.menu.unwrap();
        assert_eq!(first, 0);
        assert!(terminal.backend().to_string().contains("Filter by state"));
        assert_terminal_colors(terminal.backend());
        app.on_mouse(click(menu.x + 1, menu.y + 1));
        assert!(app.overlay.is_none());
        assert_eq!(app.pane().state_filter.as_deref(), Some("Pending"));
        assert_eq!(app.pane().matches.len(), 2);
    }

    fn assert_terminal_colors(backend: &TestBackend) {
        assert!(backend.buffer().content().iter().all(|cell| {
            cell.bg == Color::Reset && !matches!(cell.fg, Color::Rgb(..) | Color::Indexed(_))
        }));
    }
}
