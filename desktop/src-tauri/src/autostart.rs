//! Start with the Windows session (HKCU `...\CurrentVersion\Run` entry, written by
//! tauri-plugin-autostart). Off by default; the user turns it on from the tray or settings.

use tauri::{AppHandle, Runtime};
use tauri_plugin_autostart::ManagerExt;

/// Passed when Windows starts the app at login (useful in logs; the app behaves the same).
pub const LAUNCH_ARG: &str = "--autostart";

pub fn plugin<R: Runtime>() -> tauri::plugin::TauriPlugin<R> {
    tauri_plugin_autostart::Builder::new()
        .arg(LAUNCH_ARG)
        .build()
}

pub fn is_enabled<R: Runtime>(app: &AppHandle<R>) -> bool {
    app.autolaunch().is_enabled().unwrap_or_else(|err| {
        log::warn!("autostart state unknown: {err}");
        false
    })
}

pub fn set<R: Runtime>(app: &AppHandle<R>, enabled: bool) -> Result<(), String> {
    let manager = app.autolaunch();
    let result = if enabled {
        manager.enable()
    } else {
        manager.disable()
    };
    result.map_err(|e| e.to_string())
}
