//! Desktop settings, stored as JSON in the OS app-config dir
//! (Windows: `%APPDATA%\com.yaver.desktop\config.json`).
//!
//! The user edits this file by hand (app limits), so the app never writes a stale
//! in-memory copy over it: every save re-reads the file and changes only its own field.

use crate::screentime::limits::AppLimit;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

pub const FILE_NAME: &str = "config.json";

fn default_true() -> bool {
    true
}

fn default_idle_minutes() -> u32 {
    5
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    /// Backend address (normalized, no trailing slash); `None` = `api::DEFAULT_API_URL`.
    pub api_url: Option<String>,
    /// Last place the logo was dragged to (physical px); `None` = bottom-right corner.
    pub bubble_position: Option<(i32, i32)>,
    /// Sample the foreground app every 5 s into the local SQLite file.
    #[serde(default = "default_true")]
    pub track_screen_time: bool,
    /// No keyboard/mouse input for this long = idle (not counted). Apps with a limit
    /// count anyway: a game played with a controller is not idle.
    #[serde(default = "default_idle_minutes")]
    pub idle_minutes: u32,
    /// Daily limits; warnings at 80 % and 100 %, nothing is closed.
    pub app_limits: Vec<AppLimit>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            api_url: None,
            bubble_position: None,
            track_screen_time: true,
            idle_minutes: default_idle_minutes(),
            app_limits: Vec::new(),
        }
    }
}

pub fn path(config_dir: &Path) -> PathBuf {
    config_dir.join(FILE_NAME)
}

/// `Ok(None)`: no file yet. `Err`: the file exists but isn't valid (shown in settings).
pub fn read(config_dir: &Path) -> Result<Option<Config>, String> {
    match fs::read_to_string(path(config_dir)) {
        Ok(text) => serde_json::from_str(&text)
            .map(Some)
            .map_err(|err| err.to_string()),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(err.to_string()),
    }
}

pub fn save(config_dir: &Path, config: &Config) -> std::io::Result<()> {
    fs::create_dir_all(config_dir)?;
    let text = serde_json::to_string_pretty(config).map_err(std::io::Error::other)?;
    // Write-then-rename so a crash mid-write never leaves half a file.
    let tmp = config_dir.join(format!("{FILE_NAME}.tmp"));
    fs::write(&tmp, text + "\n")?;
    fs::rename(tmp, path(config_dir))
}

/// Read-modify-write: applies `change` to what is on disk now. Refuses to touch a file
/// it can't parse (the user is probably mid-edit) instead of replacing it with defaults.
pub fn update(config_dir: &Path, change: impl FnOnce(&mut Config)) -> Result<Config, String> {
    let mut config = read(config_dir)?.unwrap_or_default();
    change(&mut config);
    save(config_dir, &config).map_err(|err| err.to_string())?;
    Ok(config)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("yaver-desktop-test-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        dir
    }

    #[test]
    fn missing_file_is_not_an_error() {
        assert_eq!(read(&temp_dir("missing")), Ok(None));
    }

    #[test]
    fn round_trips() {
        let dir = temp_dir("roundtrip");
        let config = Config {
            api_url: Some("http://pc.tail1234.ts.net:8080".into()),
            bubble_position: Some((-300, 40)),
            app_limits: vec![AppLimit {
                name: "VALORANT".into(),
                processes: vec!["VALORANT-Win64-Shipping.exe".into()],
                daily_minutes: 90,
            }],
            ..Config::default()
        };
        save(&dir, &config).unwrap();
        assert_eq!(read(&dir), Ok(Some(config)));
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn broken_file_is_reported_and_left_alone() {
        let dir = temp_dir("broken");
        fs::create_dir_all(&dir).unwrap();
        fs::write(path(&dir), "{not json").unwrap();
        assert!(read(&dir).is_err());
        assert!(update(&dir, |c| c.bubble_position = Some((1, 2))).is_err());
        assert_eq!(fs::read_to_string(path(&dir)).unwrap(), "{not json");
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn update_keeps_hand_edits() {
        let dir = temp_dir("handedit");
        save(&dir, &Config::default()).unwrap();
        // The user adds a limit by hand while the app is running…
        fs::write(
            path(&dir),
            r#"{"app_limits": [{"name": "X", "processes": ["x.exe"], "daily_minutes": 10}]}"#,
        )
        .unwrap();
        // …then drags the logo: the limit must survive.
        let saved = update(&dir, |c| c.bubble_position = Some((5, 6))).unwrap();
        assert_eq!(saved.app_limits.len(), 1);
        assert_eq!(read(&dir).unwrap().unwrap().app_limits.len(), 1);
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn example_file_parses() {
        let example: Config =
            serde_json::from_str(include_str!("../../config.example.json")).unwrap();
        assert_eq!(example.app_limits[0].daily_minutes, 90);
    }

    #[test]
    fn missing_fields_get_defaults() {
        let config: Config = serde_json::from_str(r#"{"future_field": 1}"#).unwrap();
        assert_eq!(config, Config::default());
        assert!(config.track_screen_time);
        assert_eq!(config.idle_minutes, 5);
    }
}
