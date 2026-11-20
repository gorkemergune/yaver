//! Window placement math, kept free of Tauri types so it can be unit tested.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

impl Rect {
    pub fn contains(&self, x: i32, y: i32) -> bool {
        x >= self.x && y >= self.y && x < self.x + self.w && y < self.y + self.h
    }
}

/// Gap between the logo and the chat panel / the screen edge (physical px).
pub const GAP: i32 = 12;

/// Where the logo starts on first run: bottom-right corner of the work area.
pub fn default_bubble_position(
    area: Rect,
    bubble_w: i32,
    bubble_h: i32,
    margin: i32,
) -> (i32, i32) {
    (
        area.x + area.w - bubble_w - margin,
        area.y + area.h - bubble_h - margin,
    )
}

/// Puts the panel next to the logo: to its left if it fits, otherwise to its right,
/// bottoms aligned; always clamped inside the work area.
pub fn place_panel(anchor: Rect, panel_w: i32, panel_h: i32, area: Rect) -> (i32, i32) {
    let left = anchor.x - GAP - panel_w;
    let x = if left >= area.x {
        left
    } else {
        anchor.x + anchor.w + GAP
    };
    let y = anchor.y + anchor.h - panel_h;
    (
        clamp(x, area.x, area.x + area.w - panel_w),
        clamp(y, area.y, area.y + area.h - panel_h),
    )
}

/// Puts a notice balloon above the logo, right edges aligned (below it if there is no
/// room above); always clamped inside the work area.
pub fn place_notice(anchor: Rect, notice_w: i32, notice_h: i32, area: Rect) -> (i32, i32) {
    let x = anchor.x + anchor.w - notice_w;
    let above = anchor.y - GAP / 2 - notice_h;
    let y = if above >= area.y {
        above
    } else {
        anchor.y + anchor.h + GAP / 2
    };
    (
        clamp(x, area.x, area.x + area.w - notice_w),
        clamp(y, area.y, area.y + area.h - notice_h),
    )
}

/// Like `i32::clamp`, but a panel bigger than the area sticks to the area's start
/// instead of panicking.
fn clamp(value: i32, min: i32, max: i32) -> i32 {
    value.min(max).max(min)
}

#[cfg(test)]
mod tests {
    use super::*;

    const SCREEN: Rect = Rect {
        x: 0,
        y: 0,
        w: 1920,
        h: 1040,
    };

    #[test]
    fn default_position_is_bottom_right() {
        assert_eq!(default_bubble_position(SCREEN, 72, 72, 24), (1824, 944));
    }

    #[test]
    fn panel_opens_left_of_logo_with_bottoms_aligned() {
        let logo = Rect {
            x: 1824,
            y: 944,
            w: 72,
            h: 72,
        };
        assert_eq!(
            place_panel(logo, 360, 520, SCREEN),
            (1824 - GAP - 360, 944 + 72 - 520)
        );
    }

    #[test]
    fn panel_flips_right_near_left_edge() {
        let logo = Rect {
            x: 20,
            y: 600,
            w: 72,
            h: 72,
        };
        assert_eq!(place_panel(logo, 360, 520, SCREEN).0, 20 + 72 + GAP);
    }

    #[test]
    fn panel_stays_on_screen_near_top() {
        let logo = Rect {
            x: 1000,
            y: 10,
            w: 72,
            h: 72,
        };
        assert_eq!(place_panel(logo, 360, 520, SCREEN).1, 0);
    }

    #[test]
    fn works_on_a_secondary_monitor_left_of_primary() {
        let second = Rect {
            x: -1280,
            y: 0,
            w: 1280,
            h: 1000,
        };
        let logo = Rect {
            x: -100,
            y: 900,
            w: 72,
            h: 72,
        };
        let (x, y) = place_panel(logo, 360, 520, second);
        assert_eq!((x, y), (-100 - GAP - 360, 900 + 72 - 520));
    }

    #[test]
    fn notice_sits_above_logo_right_aligned() {
        let logo = Rect {
            x: 1824,
            y: 944,
            w: 72,
            h: 72,
        };
        assert_eq!(
            place_notice(logo, 300, 96, SCREEN),
            (1824 + 72 - 300, 944 - GAP / 2 - 96)
        );
    }

    #[test]
    fn notice_goes_below_logo_at_the_top_edge() {
        let logo = Rect {
            x: 10,
            y: 10,
            w: 72,
            h: 72,
        };
        assert_eq!(place_notice(logo, 300, 96, SCREEN), (0, 10 + 72 + GAP / 2));
    }

    #[test]
    fn oversized_panel_sticks_to_area_start() {
        let tiny = Rect {
            x: 0,
            y: 0,
            w: 200,
            h: 200,
        };
        let logo = Rect {
            x: 100,
            y: 100,
            w: 72,
            h: 72,
        };
        assert_eq!(place_panel(logo, 360, 520, tiny), (0, 0));
    }
}
