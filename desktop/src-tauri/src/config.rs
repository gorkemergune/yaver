//! Desktop settings, stored as JSON in the OS app-config dir
//! (Windows: `%APPDATA%\com.yaver.desktop\config.json`).

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

pub const FILE_NAME: &str = "config.json";

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    /// Backend address (normalized, no trailing slash); `None` = `api::DEFAULT_API_URL`.
    pub api_url: Option<String>,
    /// Last place the logo was dragged to (physical px); `None` = bottom-right corner.
    pub bubble_position: Option<(i32, i32)>,
}

pub fn path(config_dir: &Path) -> PathBuf {
    config_dir.join(FILE_NAME)
}

/// A missing or broken file falls back to the defaults (a broken one is logged, not fatal).
pub fn load(config_dir: &Path) -> Config {
    let file = path(config_dir);
    match fs::read_to_string(&file) {
        Ok(text) => serde_json::from_str(&text).unwrap_or_else(|err| {
            log::warn!("ignoring unreadable {}: {err}", file.display());
            Config::default()
        }),
        Err(_) => Config::default(),
    }
}

pub fn save(config_dir: &Path, config: &Config) -> std::io::Result<()> {
    fs::create_dir_all(config_dir)?;
    let text = serde_json::to_string_pretty(config).map_err(std::io::Error::other)?;
    // Write-then-rename so a crash mid-write never leaves half a file.
    let tmp = config_dir.join(format!("{FILE_NAME}.tmp"));
    fs::write(&tmp, text)?;
    fs::rename(tmp, path(config_dir))
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
    fn missing_file_gives_defaults() {
        assert_eq!(load(&temp_dir("missing")), Config::default());
    }

    #[test]
    fn round_trips() {
        let dir = temp_dir("roundtrip");
        let config = Config {
            api_url: Some("http://pc.tail1234.ts.net:8080".into()),
            bubble_position: Some((-300, 40)),
        };
        save(&dir, &config).unwrap();
        assert_eq!(load(&dir), config);
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn broken_file_gives_defaults() {
        let dir = temp_dir("broken");
        fs::create_dir_all(&dir).unwrap();
        fs::write(path(&dir), "{not json").unwrap();
        assert_eq!(load(&dir), Config::default());
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn unknown_fields_are_tolerated() {
        let config: Config = serde_json::from_str(r#"{"future_field": 1}"#).unwrap();
        assert_eq!(config, Config::default());
    }
}
