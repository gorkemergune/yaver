mod config;
mod layout;
mod windows;

use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Manager, WindowEvent};

/// Settings in memory + where they live on disk.
pub struct AppState {
    config_dir: PathBuf,
    config: Mutex<config::Config>,
    /// Bumped on every logo move; a save only runs if no newer move came in meanwhile.
    move_generation: AtomicU64,
}

impl AppState {
    fn save(&self) {
        let config = self.config.lock().expect("config lock").clone();
        if let Err(err) = config::save(&self.config_dir, &config) {
            log::warn!("could not save settings: {err}");
        }
    }
}

/// While the logo is dragged, `Moved` fires many times a second; write once it settles.
const MOVE_SAVE_DELAY: Duration = Duration::from_millis(600);

fn remember_bubble_position(app: &AppHandle, x: i32, y: i32) {
    let state = app.state::<AppState>();
    state.config.lock().expect("config lock").bubble_position = Some((x, y));
    let generation = state.move_generation.fetch_add(1, Ordering::SeqCst) + 1;
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(MOVE_SAVE_DELAY).await;
        let state = app.state::<AppState>();
        if state.move_generation.load(Ordering::SeqCst) == generation {
            state.save();
        }
    });
}

#[tauri::command]
fn toggle_chat(app: AppHandle) -> Result<(), String> {
    windows::toggle_chat(&app).map_err(|e| e.to_string())
}

#[tauri::command]
fn hide_chat(app: AppHandle) -> Result<(), String> {
    windows::hide_chat(&app).map_err(|e| e.to_string())
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let config_dir = app.path().app_config_dir()?;
            let config = config::load(&config_dir);
            let saved_position = config.bubble_position;
            app.manage(AppState {
                config_dir,
                config: Mutex::new(config),
                move_generation: AtomicU64::new(0),
            });
            windows::show_bubble(app.handle(), saved_position)?;
            Ok(())
        })
        .on_window_event(|window, event| match event {
            WindowEvent::Moved(pos) if window.label() == windows::BUBBLE => {
                remember_bubble_position(window.app_handle(), pos.x, pos.y);
            }
            // Closing the chat (Alt+F4) only hides it; the app lives on in the logo.
            WindowEvent::CloseRequested { api, .. } if window.label() == windows::CHAT => {
                api.prevent_close();
                let _ = window.hide();
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![toggle_chat, hide_chat])
        .run(tauri::generate_context!())
        .expect("error while running Yaver desktop");
}
