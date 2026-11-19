//! The two windows: the floating logo ("bubble") and the mini chat panel ("chat").

use crate::layout::{self, Rect};
use tauri::{AppHandle, Manager, PhysicalPosition, Runtime, WebviewWindow};

pub const BUBBLE: &str = "bubble";
pub const CHAT: &str = "chat";

const BUBBLE_MARGIN: i32 = 24;

fn window<R: Runtime>(app: &AppHandle<R>, label: &str) -> tauri::Result<WebviewWindow<R>> {
    app.get_webview_window(label)
        .ok_or(tauri::Error::WindowNotFound)
}

fn work_area(monitor: &tauri::Monitor) -> Rect {
    let area = monitor.work_area();
    Rect {
        x: area.position.x,
        y: area.position.y,
        w: area.size.width as i32,
        h: area.size.height as i32,
    }
}

fn bounds<R: Runtime>(window: &WebviewWindow<R>) -> tauri::Result<Rect> {
    let pos = window.outer_position()?;
    let size = window.outer_size()?;
    Ok(Rect {
        x: pos.x,
        y: pos.y,
        w: size.width as i32,
        h: size.height as i32,
    })
}

/// Puts the logo where it was left, or bottom-right of the primary screen if that spot
/// is gone (e.g. the monitor it was on is unplugged), then shows it.
pub fn show_bubble<R: Runtime>(app: &AppHandle<R>, saved: Option<(i32, i32)>) -> tauri::Result<()> {
    let bubble = window(app, BUBBLE)?;
    let size = bubble.outer_size()?;
    let (w, h) = (size.width as i32, size.height as i32);
    let monitors = bubble.available_monitors()?;
    let on_screen = |(x, y): (i32, i32)| {
        monitors
            .iter()
            .any(|m| work_area(m).contains(x + w / 2, y + h / 2))
    };
    let position = match saved.filter(|p| on_screen(*p)) {
        Some(p) => Some(p),
        None => bubble
            .primary_monitor()?
            .map(|m| layout::default_bubble_position(work_area(&m), w, h, BUBBLE_MARGIN)),
    };
    if let Some((x, y)) = position {
        bubble.set_position(PhysicalPosition::new(x, y))?;
    }
    bubble.show()
}

/// Shows the chat next to the logo, or hides it if it is already open.
pub fn toggle_chat<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let chat = window(app, CHAT)?;
    if chat.is_visible()? {
        return chat.hide();
    }
    show_chat(app)
}

pub fn show_chat<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let chat = window(app, CHAT)?;
    let bubble = window(app, BUBBLE)?;
    let anchor = bounds(&bubble)?;
    let monitor = match bubble.current_monitor()? {
        Some(m) => Some(m),
        None => bubble.primary_monitor()?,
    };
    if let Some(monitor) = monitor {
        let panel = chat.outer_size()?;
        let (x, y) = layout::place_panel(
            anchor,
            panel.width as i32,
            panel.height as i32,
            work_area(&monitor),
        );
        chat.set_position(PhysicalPosition::new(x, y))?;
    }
    chat.show()?;
    chat.unminimize()?;
    chat.set_focus()
}

pub fn hide_chat<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    window(app, CHAT)?.hide()
}
