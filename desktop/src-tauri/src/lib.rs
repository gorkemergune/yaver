mod api;
mod config;
mod layout;
mod windows;

use serde::Serialize;
use serde_json::Value;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Manager, State, WindowEvent};

/// Settings in memory + where they live on disk.
pub struct AppState {
    config_dir: PathBuf,
    config: Mutex<config::Config>,
    /// Bumped on every logo move; a save only runs if no newer move came in meanwhile.
    move_generation: AtomicU64,
    api: api::Client,
}

impl AppState {
    fn save(&self) -> std::io::Result<()> {
        let config = self.config.lock().expect("config lock").clone();
        config::save(&self.config_dir, &config)
    }

    fn save_or_log(&self) {
        if let Err(err) = self.save() {
            log::warn!("could not save settings: {err}");
        }
    }

    /// `YAVER_API_URL` wins over the saved address, which wins over the default.
    fn api_url(&self) -> String {
        env_api_url().unwrap_or_else(|| {
            self.config
                .lock()
                .expect("config lock")
                .api_url
                .clone()
                .unwrap_or_else(|| api::DEFAULT_API_URL.to_owned())
        })
    }
}

fn env_api_url() -> Option<String> {
    let raw = std::env::var(api::API_URL_ENV).ok()?;
    match api::normalize_api_url(&raw) {
        Ok(url) => Some(url),
        Err(_) => {
            log::warn!("ignoring invalid {}={raw:?}", api::API_URL_ENV);
            None
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
            state.save_or_log();
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

#[derive(Serialize)]
struct Settings {
    api_url: String,
    default_api_url: &'static str,
    /// The address comes from `YAVER_API_URL`; saving a new one has no effect until it is unset.
    api_url_from_env: bool,
}

#[tauri::command]
fn get_settings(state: State<'_, AppState>) -> Settings {
    Settings {
        api_url: state.api_url(),
        default_api_url: api::DEFAULT_API_URL,
        api_url_from_env: env_api_url().is_some(),
    }
}

/// Saves a new backend address; returns it normalized.
#[tauri::command]
fn set_api_url(state: State<'_, AppState>, url: String) -> Result<String, api::ApiError> {
    let url = api::normalize_api_url(&url)?;
    state.config.lock().expect("config lock").api_url = Some(url.clone());
    state.save().map_err(|err| api::ApiError {
        code: "save_failed",
        status: None,
        detail: Some(err.to_string()),
    })?;
    Ok(url)
}

#[tauri::command]
async fn send_chat(
    state: State<'_, AppState>,
    message: String,
    conversation_id: Option<i64>,
) -> Result<Value, api::ApiError> {
    let base = state.api_url();
    state.api.chat(&base, &message, conversation_id).await
}

#[tauri::command]
async fn undo_changes(
    state: State<'_, AppState>,
    change_set_id: String,
) -> Result<Value, api::ApiError> {
    let base = state.api_url();
    state.api.undo(&base, &change_set_id).await
}

#[tauri::command]
async fn get_team(state: State<'_, AppState>) -> Result<Value, api::ApiError> {
    let base = state.api_url();
    state.api.team(&base).await
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
                api: api::Client::new(),
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
        .invoke_handler(tauri::generate_handler![
            toggle_chat,
            hide_chat,
            get_settings,
            set_api_url,
            send_chat,
            undo_changes,
            get_team
        ])
        .run(tauri::generate_context!())
        .expect("error while running Yaver desktop");
}
