//! The backend login token (when the server has `APP_PASSWORD`). Kept in its own file next
//! to config.json, which the user edits by hand: `%APPDATA%\com.yaver.desktop\session.json`.

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

pub const FILE_NAME: &str = "session.json";

#[derive(Serialize, Deserialize)]
struct Stored {
    token: String,
}

pub fn path(config_dir: &Path) -> PathBuf {
    config_dir.join(FILE_NAME)
}

/// The saved token; none (or an unreadable file) = not logged in.
pub fn load(config_dir: &Path) -> Option<String> {
    let text = fs::read_to_string(path(config_dir)).ok()?;
    let stored: Stored = serde_json::from_str(&text).ok()?;
    Some(stored.token).filter(|t| !t.is_empty())
}

/// `None` deletes the file (logout).
pub fn save(config_dir: &Path, token: Option<&str>) -> std::io::Result<()> {
    match token {
        Some(token) => {
            fs::create_dir_all(config_dir)?;
            let tmp = config_dir.join(format!("{FILE_NAME}.tmp"));
            let text = serde_json::to_string(&Stored {
                token: token.to_owned(),
            })
            .map_err(std::io::Error::other)?;
            fs::write(&tmp, text)?;
            fs::rename(tmp, path(config_dir))
        }
        None => match fs::remove_file(path(config_dir)) {
            Err(err) if err.kind() != std::io::ErrorKind::NotFound => Err(err),
            _ => Ok(()),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn saves_loads_and_forgets_the_token() {
        let dir = std::env::temp_dir().join(format!("yaver-session-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        assert_eq!(load(&dir), None);
        save(&dir, Some("abc")).unwrap();
        assert_eq!(load(&dir).as_deref(), Some("abc"));
        save(&dir, None).unwrap();
        assert_eq!(load(&dir), None);
        save(&dir, None).unwrap(); // already gone: fine
        fs::write(path(&dir), "{broken").unwrap();
        assert_eq!(load(&dir), None);
        let _ = fs::remove_dir_all(&dir);
    }
}
