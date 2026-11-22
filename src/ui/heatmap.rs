use std::ops::Range;

use ratatui::{
    Frame,
    layout::{
        Constraint::{Fill, Length},
        Layout, Rect,
    },
    text::{Line, Span},
};

use super::{
    ACCENT, AMBER, BLUE, GREEN, TEXT, bold, fg, inset, muted, nonempty, pane, partition_color,
    partition_meter,
};
use crate::{
    app::{Pane, Record},
    model::{Partition, quantity},
};

const GLYPHS: [&str; 3] = ["■", "□", "▧"];
const COLORS: [ratatui::style::Color; 3] = [BLUE, GREEN, AMBER];
const LABELS: [&str; 3] = ["Used", "Idle", "Other"];
const TILES_PER_ROW: usize = 8;
const GRID_ROWS: u16 = 3;
const CARD_HEIGHT: u16 = GRID_ROWS + 1;
const FRAME_HEIGHT: u16 = 3;

pub(super) fn draw(frame: &mut Frame<'_>, data: &Pane, mut area: Rect) -> Vec<(Rect, usize)> {
    let cards = area.width >= 84 && area.height >= FRAME_HEIGHT + CARD_HEIGHT;
    let count = data.matches.len();
    let ideal_height = if count == 0 {
        5
    } else if cards {
        count
            .div_ceil(2)
            .saturating_mul(usize::from(CARD_HEIGHT + 1))
            + usize::from(FRAME_HEIGHT - 1)
    } else {
        count + usize::from(FRAME_HEIGHT)
    };
    area.height = area
        .height
        .min(u16::try_from(ideal_height).unwrap_or(u16::MAX));

    let block = pane("Partition heatmap", false);
    let inside = inset(block.inner(area), 1, 0);
    frame.render_widget(block, area);
    if count == 0 {
        let message = if data.error.is_some() && data.data.is_none() {
            "Partition data unavailable"
        } else if data.data.is_none() {
            "Waiting for partition data…"
        } else if data.is_filtered() {
            "No partitions match the current filters"
        } else {
            "No partitions to display"
        };
        frame.render_widget(Line::from(muted(message)).centered(), inside);
        return Vec::new();
    }

    let [legend, grid] = Layout::vertical([Length(1), Fill(1)]).areas(inside);
    let selected = data.table.selected().unwrap_or(0);
    let shown = if cards {
        draw_cards(frame, data, grid, selected)
    } else {
        draw_rows(frame, data, grid, selected)
    };

    let mut key = vec![
        fg(GLYPHS[0], BLUE),
        muted(" Used  "),
        fg(GLYPHS[1], GREEN),
        muted(" Idle  "),
        fg(GLYPHS[2], AMBER),
        muted(" Other"),
    ];
    if legend.width >= 52 {
        key.push(muted("   ·   Share of each partition"));
    }
    let line = Line::from(key);
    if shown.len() < count
        && let (Some((_, first)), Some((_, last))) = (shown.first(), shown.last())
    {
        let position = format!("{}–{} of {count}", first + 1, last + 1);
        if usize::from(legend.width) > line.width() + position.chars().count() + 1 {
            frame.render_widget(Line::from(muted(position)).right_aligned(), legend);
        }
    }
    frame.render_widget(line, legend);
    shown
}

fn draw_rows(
    frame: &mut Frame<'_>,
    data: &Pane,
    area: Rect,
    selected: usize,
) -> Vec<(Rect, usize)> {
    let names = (area.width / 3).clamp(8, 22);
    let layout = Layout::horizontal([Length(names), Fill(1), Length(9)]);
    let mut hits = Vec::new();
    for (offset, index) in page(data.matches.len(), usize::from(area.height), selected).enumerate()
    {
        let Some(Record::Partition(part)) = data.row(data.matches[index]) else {
            continue;
        };
        let row = Rect::new(area.x, area.y + offset as u16, area.width, 1);
        let [label, map, total] = layout.areas(row);
        let budget = usize::from(map.width / 2).min(24);
        let tiles = proportional_tiles(allocation(part), budget);
        frame.render_widget(partition_label(part, index == selected), label);
        frame.render_widget(Line::from(tile_spans(tiles)), map);
        frame.render_widget(
            Line::from(muted(quantity(part.total))).right_aligned(),
            total,
        );
        hits.push((row, index));
    }
    hits
}

fn draw_cards(
    frame: &mut Frame<'_>,
    data: &Pane,
    area: Rect,
    selected: usize,
) -> Vec<(Rect, usize)> {
    let groups = data.matches.len().div_ceil(2);
    let shown = groups.min(usize::from(area.height / CARD_HEIGHT));
    let row_gap = u16::from(usize::from(area.height) >= shown * usize::from(CARD_HEIGHT + 1) - 1);
    let layout = Layout::horizontal([Fill(1), Length(4), Fill(1)]);
    let mut hits = Vec::new();
    for (offset, group) in page(groups, shown, selected / 2).enumerate() {
        let y = area.y + offset as u16 * (CARD_HEIGHT + row_gap);
        let row = Rect::new(area.x, y, area.width, CARD_HEIGHT);
        let [left, _, right] = layout.areas(row);
        for (col, card) in [left, right].into_iter().enumerate() {
            let index = group * 2 + col;
            let part = data
                .matches
                .get(index)
                .and_then(|&matched| data.row(matched));
            if let Some(Record::Partition(part)) = part {
                draw_card(frame, part, card, index == selected);
                hits.push((card, index));
            }
        }
    }
    hits
}

fn draw_card(frame: &mut Frame<'_>, part: &Partition, area: Rect, selected: bool) {
    let [title, body] = Layout::vertical([Length(1), Fill(1)]).areas(area);
    let state = nonempty(&part.state);
    let total = format!(" · {} nodes", quantity(part.total));
    let right_width = title
        .width
        .saturating_sub(12)
        .min((state.chars().count() + total.len()) as u16);
    let [label, details] = Layout::horizontal([Fill(1), Length(right_width)]).areas(title);
    frame.render_widget(partition_label(part, selected), label);
    let color = partition_color(&state);
    frame.render_widget(
        Line::from(vec![fg(state, color), muted(total)]).right_aligned(),
        details,
    );

    let counts = allocation(part);
    let mut remaining = proportional_tiles(counts, TILES_PER_ROW * usize::from(GRID_ROWS));
    let [grid, shares] = Layout::horizontal([Length(20), Fill(1)]).areas(body);
    for (line, ((label, count), color)) in LABELS.into_iter().zip(counts).zip(COLORS).enumerate() {
        if part.total == 0 && line == 0 {
            frame.render_widget(Line::from(muted("  No nodes")), grid);
            break;
        }

        let mut available = TILES_PER_ROW;
        let tiles = remaining.each_mut().map(|count| {
            let shown = (*count).min(available);
            *count -= shown;
            available -= shown;
            shown
        });
        let grid_row = Rect::new(grid.x + 2, grid.y + line as u16, grid.width - 2, 1);
        let share_row = Rect::new(shares.x, shares.y + line as u16, shares.width, 1);
        frame.render_widget(Line::from(tile_spans(tiles)), grid_row);
        frame.render_widget(
            Line::from(vec![
                muted(format!("{label:<5} ")),
                fg(format!("{:>4}", percentage(count, part.total)), color),
            ]),
            share_row,
        );
    }
}

fn partition_label(part: &Partition, selected: bool) -> Line<'_> {
    let marker = if selected { "› " } else { "  " };
    let name = if selected {
        bold(part.name.as_str(), ACCENT)
    } else {
        fg(part.name.as_str(), TEXT)
    };
    Line::from(vec![fg(marker, ACCENT), name])
}

fn page(len: usize, capacity: usize, selected: usize) -> Range<usize> {
    let width = len.min(capacity);
    if width == 0 {
        return 0..0;
    }
    let start = (selected / width * width).min(len - width);
    start..start + width
}

fn tile_spans(tiles: [usize; 3]) -> Vec<Span<'static>> {
    tiles
        .into_iter()
        .zip(GLYPHS)
        .zip(COLORS)
        .filter(|&((count, _), _)| count != 0)
        .map(|((count, glyph), color)| fg(format!("{glyph} ").repeat(count), color))
        .collect()
}

fn allocation(part: &Partition) -> [u64; 3] {
    partition_meter(part.used, part.idle, part.total).map(|(count, _)| count)
}

fn percentage(count: u64, total: u64) -> String {
    if total == 0 {
        return "—".into();
    }
    let rounded = (u128::from(count) * 100 + u128::from(total / 2)) / u128::from(total);
    match rounded {
        0 if count > 0 => "<1%".into(),
        100 if count < total => ">99%".into(),
        _ => format!("{rounded}%"),
    }
}

fn proportional_tiles(counts: [u64; 3], budget: usize) -> [usize; 3] {
    let total: u128 = counts.into_iter().map(u128::from).sum();
    if total == 0 {
        return [0; 3];
    }

    let products = counts.map(|count| u128::from(count) * budget as u128);
    let mut tiles = products.map(|product| (product / total) as usize);
    let mut order = [0, 1, 2];
    order.sort_by_key(|&index| std::cmp::Reverse(products[index] % total));
    for index in order.into_iter().take(budget - tiles.iter().sum::<usize>()) {
        tiles[index] += 1;
    }
    tiles
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tile_budget_is_equal_for_large_and_small_partitions() {
        assert_eq!(proportional_tiles([54, 81, 7], 24), [9, 14, 1]);
        assert_eq!(proportional_tiles([44, 31, 679], 24), [1, 1, 22]);
        assert_eq!(proportional_tiles([1, 1, 0], 24), [12, 12, 0]);
        assert_eq!(proportional_tiles([0, 0, 2], 24), [0, 0, 24]);
        assert_eq!(proportional_tiles([0; 3], 24), [0; 3]);
    }

    #[test]
    fn percentages_distinguish_small_shares_from_zero() {
        assert_eq!(percentage(679, 754), "90%");
        assert_eq!(percentage(1, 754), "<1%");
        assert_eq!(percentage(753, 754), ">99%");
        assert_eq!(percentage(0, 2), "0%");
        assert_eq!(percentage(2, 2), "100%");
    }

    #[test]
    fn page_tracks_the_selected_partition() {
        assert_eq!(page(8, 3, 0), 0..3);
        assert_eq!(page(8, 3, 7), 5..8);
        assert_eq!(page(2, 8, 1), 0..2);
    }
}
