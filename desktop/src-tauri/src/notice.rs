//! Notice balloon next to the logo (limit warnings for now; briefings later), plus the
//! same text as a Windows notification: a game in fullscreen can hide the balloon.

use crate::layout::{self, Rect};
use crate::windows::{self, BUBBLE, CHAT};
use serde::Serialize;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, Runtime};
use tauri_plugin_notification::NotificationExt;

pub const NOTICE: &str = "notice";

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Notice {
    pub title: String,
    pub body: String,
}

/// The notice on screen; the page asks for it when it loads (it may miss the event).
#[derive(Default)]
pub struct Current(Mutex<Option<Notice>>);

fn place<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let (Some(window), Some(bubble)) = (
        app.get_webview_window(NOTICE),
        app.get_webview_window(BUBBLE),
    ) else {
        return Ok(());
    };
    let pos = bubble.outer_position()?;
    let size = bubble.outer_size()?;
    let anchor = Rect {
        x: pos.x,
        y: pos.y,
        w: size.width as i32,
        h: size.height as i32,
    };
    let monitor = match bubble.current_monitor()? {
        Some(m) => Some(m),
        None => bubble.primary_monitor()?,
    };
    if let Some(monitor) = monitor {
        let area = monitor.work_area();
        let area = Rect {
            x: area.position.x,
            y: area.position.y,
            w: area.size.width as i32,
            h: area.size.height as i32,
        };
        let own = window.outer_size()?;
        let (x, y) = layout::place_notice(anchor, own.width as i32, own.height as i32, area);
        window.set_position(PhysicalPosition::new(x, y))?;
    }
    // Not focused: it must not pull a game or the editor out of the foreground.
    window.show()
}

pub fn show(app: &AppHandle, notice: Notice) {
    *app.state::<Current>().0.lock().expect("notice lock") = Some(notice.clone());
    if let Err(err) = place(app) {
        log::warn!("notice window: {err}");
    }
    let _ = app.emit_to(NOTICE, "notice", &notice);
    if let Err(err) = app
        .notification()
        .builder()
        .title(&notice.title)
        .body(&notice.body)
        .show()
    {
        log::warn!("system notification: {err}");
    }
}

#[tauri::command]
pub fn current_notice(state: tauri::State<'_, Current>) -> Option<Notice> {
    state.0.lock().expect("notice lock").clone()
}

#[tauri::command]
pub fn dismiss_notice(app: AppHandle) -> Result<(), String> {
    *app.state::<Current>().0.lock().expect("notice lock") = None;
    match app.get_webview_window(NOTICE) {
        Some(window) => window.hide().map_err(|e| e.to_string()),
        None => Ok(()),
    }
}

/// Clicking the balloon opens the chat panel on the screen-time view.
#[tauri::command]
pub fn open_notice(app: AppHandle) -> Result<(), String> {
    dismiss_notice(app.clone())?;
    windows::show_chat(&app).map_err(|e| e.to_string())?;
    app.emit_to(CHAT, "show_view", "screen")
        .map_err(|e| e.to_string())
}
