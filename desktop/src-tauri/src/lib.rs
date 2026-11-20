mod api;
mod autostart;
mod config;
mod layout;
mod notice;
mod screentime;
mod session;
mod tray;
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
    /// Last good copy of config.json.
    config: Mutex<config::Config>,
    /// Why config.json couldn't be read, if it couldn't (shown in the panel).
    config_error: Mutex<Option<String>>,
    /// Bumped on every logo move; a save only runs if no newer move came in meanwhile.
    move_generation: AtomicU64,
    api: api::Client,
}

impl AppState {
    fn new(config_dir: PathBuf) -> Self {
        let (config, error) = match config::read(&config_dir) {
            Ok(Some(config)) => (config, None),
            Ok(None) => {
                // First run: write the defaults so there is a file to add limits to.
                let config = config::Config::default();
                if let Err(err) = config::save(&config_dir, &config) {
                    log::warn!("could not create config.json: {err}");
                }
                (config, None)
            }
            Err(err) => {
                log::warn!("config.json unreadable, using defaults: {err}");
                (config::Config::default(), Some(err))
            }
        };
        let token = session::load(&config_dir);
        Self {
            config_dir,
            config: Mutex::new(config),
            config_error: Mutex::new(error),
            move_generation: AtomicU64::new(0),
            api: api::Client::new(token),
        }
    }

    pub fn config(&self) -> config::Config {
        self.config.lock().expect("config lock").clone()
    }

    pub fn config_error(&self) -> Option<String> {
        self.config_error.lock().expect("config error lock").clone()
    }

    pub fn config_path(&self) -> PathBuf {
        config::path(&self.config_dir)
    }

    /// Changes one field on disk (keeping hand edits) and in memory.
    fn update_config(&self, change: impl FnOnce(&mut config::Config)) -> Result<(), String> {
        let mut memory = self.config.lock().expect("config lock");
        let result = config::update(&self.config_dir, change);
        let mut error = self.config_error.lock().expect("config error lock");
        match result {
            Ok(saved) => {
                *memory = saved;
                *error = None;
                Ok(())
            }
            Err(err) => {
                *error = Some(err.clone());
                Err(err)
            }
        }
    }

    /// Picks up hand edits (limits); a broken file keeps the last good settings.
    pub fn reload_config(&self) {
        let mut memory = self.config.lock().expect("config lock");
        let mut error = self.config_error.lock().expect("config error lock");
        match config::read(&self.config_dir) {
            Ok(Some(config)) => {
                if *memory != config {
                    log::info!("config.json reloaded");
                }
                *memory = config;
                *error = None;
            }
            Ok(None) => *error = None,
            Err(err) => {
                if error.as_deref() != Some(err.as_str()) {
                    log::warn!("config.json unreadable, keeping the last good one: {err}");
                }
                *error = Some(err);
            }
        }
    }

    /// Daily screen-time summaries (see `screentime::sync`).
    pub async fn send_screen_time(&self, body: &Value) -> Result<Value, api::ApiError> {
        let base = self.api_url();
        self.api.screen_time(&base, body).await
    }

    /// `YAVER_API_URL` wins over the saved address, which wins over the default.
    fn api_url(&self) -> String {
        env_api_url().unwrap_or_else(|| {
            self.config()
                .api_url
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
    let generation = state.move_generation.fetch_add(1, Ordering::SeqCst) + 1;
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(MOVE_SAVE_DELAY).await;
        let state = app.state::<AppState>();
        if state.move_generation.load(Ordering::SeqCst) == generation {
            if let Err(err) = state.update_config(|c| c.bubble_position = Some((x, y))) {
                log::warn!("could not save the logo position: {err}");
            }
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
    /// Starts with the Windows session.
    autostart: bool,
    /// A login token is saved (the server may still have ended it).
    logged_in: bool,
}

#[tauri::command]
fn get_settings(app: AppHandle, state: State<'_, AppState>) -> Settings {
    Settings {
        api_url: state.api_url(),
        default_api_url: api::DEFAULT_API_URL,
        api_url_from_env: env_api_url().is_some(),
        autostart: autostart::is_enabled(&app),
        logged_in: state.api.has_token(),
    }
}

/// Logs in to a server with `APP_PASSWORD`; `false` = the server has no password.
#[tauri::command]
async fn login(state: State<'_, AppState>, password: String) -> Result<bool, api::ApiError> {
    let base = state.api_url();
    let device = screentime::sync::device_name();
    let token = state.api.login(&base, &password, &device).await?;
    let enabled = token.is_some();
    if let Some(token) = token {
        session::save(&state.config_dir, Some(&token)).map_err(|err| api::ApiError {
            code: "save_failed",
            status: None,
            detail: Some(err.to_string()),
        })?;
        state.api.set_token(Some(token));
    }
    Ok(enabled)
}

/// Ends the session on the server (best effort) and forgets the token here.
#[tauri::command]
async fn logout(state: State<'_, AppState>) -> Result<(), String> {
    let base = state.api_url();
    if state.api.has_token() {
        let _ = state.api.logout(&base).await;
    }
    state.api.set_token(None);
    session::save(&state.config_dir, None).map_err(|e| e.to_string())
}

/// Turns login autostart on/off; returns the resulting state.
#[tauri::command]
fn set_autostart(app: AppHandle, enabled: bool) -> Result<bool, String> {
    let result = autostart::set(&app, enabled);
    tray::sync(&app);
    result.map(|()| autostart::is_enabled(&app))
}

/// Saves a new backend address; returns it normalized.
#[tauri::command]
fn set_api_url(state: State<'_, AppState>, url: String) -> Result<String, api::ApiError> {
    let url = api::normalize_api_url(&url)?;
    let saved = url.clone();
    state
        .update_config(|c| c.api_url = Some(saved))
        .map_err(|err| api::ApiError {
            code: "save_failed",
            status: None,
            detail: Some(err),
        })?;
    Ok(url)
}

/// Shows config.json in Explorer (limits are edited there for now).
#[tauri::command]
fn open_config_folder(state: State<'_, AppState>) -> Result<(), String> {
    let path = state.config_path();
    #[cfg(windows)]
    {
        std::process::Command::new("explorer")
            .arg(format!("/select,{}", path.display()))
            .spawn()
            .map(|_| ())
            .map_err(|e| e.to_string())
    }
    #[cfg(not(windows))]
    {
        Err(format!("open {} by hand", path.display()))
    }
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
        // Must be registered first: a second launch (e.g. autostart + a manual start)
        // exits right away and just opens the chat of the running one.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            let _ = windows::reveal_bubble(app);
            let _ = windows::show_chat(app);
        }))
        .plugin(
            // %LOCALAPPDATA%\com.yaver.desktop\logs\Yaver.log (+ stdout)
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .timezone_strategy(tauri_plugin_log::TimezoneStrategy::UseLocal)
                .build(),
        )
        .plugin(autostart::plugin())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            if std::env::args().any(|arg| arg == autostart::LAUNCH_ARG) {
                log::info!("started at login");
            }
            let state = AppState::new(app.path().app_config_dir()?);
            let saved_position = state.config().bubble_position;
            app.manage(state);
            app.manage(notice::Current::default());
            match screentime::ScreenTime::open(&app.path().app_local_data_dir()?) {
                Ok(screen) => {
                    app.manage(screen);
                    screentime::start(app.handle().clone());
                    screentime::sync::start(app.handle().clone());
                }
                Err(err) => log::error!("screen time disabled, database error: {err}"),
            }
            windows::show_bubble(app.handle(), saved_position)?;
            tray::create(app.handle())?;
            Ok(())
        })
        .on_window_event(|window, event| match event {
            WindowEvent::Moved(pos) if window.label() == windows::BUBBLE => {
                remember_bubble_position(window.app_handle(), pos.x, pos.y);
            }
            // Alt+F4 only hides a window; quitting is in the tray menu.
            WindowEvent::CloseRequested { api, .. } => {
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
            set_autostart,
            send_chat,
            undo_changes,
            get_team,
            login,
            logout,
            open_config_folder,
            screentime::screen_time_today,
            notice::current_notice,
            notice::dismiss_notice,
            notice::open_notice
        ])
        .build(tauri::generate_context!())
        .expect("error while building Yaver desktop")
        .run(|app, event| {
            // Quit from the tray, Windows logoff/shutdown: send today's screen time once more.
            if let tauri::RunEvent::Exit = event {
                screentime::sync::final_sync(app);
            }
        });
}
