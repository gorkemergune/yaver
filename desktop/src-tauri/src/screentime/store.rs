//! Local SQLite store for screen time. Daily summaries go to the backend (`sync.rs`);
//! the sessions themselves stay here. Times are UTC unix seconds.
//!
//! Samples are folded into sessions: consecutive samples of the same app (and idle
//! state) extend one row instead of adding 17k rows a day.

use rusqlite::{params, Connection};
use std::path::Path;

/// A longer gap between samples (sleep, hibernate, app closed) ends the session; the gap
/// itself is not counted.
pub const MAX_GAP_SECS: i64 = 15;

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS screen_sessions (
    id          INTEGER PRIMARY KEY,
    exe         TEXT    NOT NULL,           -- as Windows reports it
    app_name    TEXT    NOT NULL,           -- exe description or file name
    started_at  INTEGER NOT NULL,           -- UTC unix seconds
    ended_at    INTEGER NOT NULL,
    idle        INTEGER NOT NULL DEFAULT 0  -- 1: no keyboard/mouse input for a while
);
CREATE INDEX IF NOT EXISTS screen_sessions_ended_at ON screen_sessions (ended_at);

-- One row per limit warning already shown, so a restart doesn't repeat it.
CREATE TABLE IF NOT EXISTS limit_alerts (
    day         TEXT    NOT NULL,           -- local date, YYYY-MM-DD
    limit_name  TEXT    NOT NULL,
    level       INTEGER NOT NULL,           -- 80 | 100 (% of the limit)
    at          INTEGER NOT NULL,
    PRIMARY KEY (day, limit_name, level)
);
-- Small key/value state; `synced_until`: last successful backend sync (unix seconds).
CREATE TABLE IF NOT EXISTS sync_state (
    key         TEXT    PRIMARY KEY,
    value       INTEGER NOT NULL
);
PRAGMA user_version = 2;
";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Sample {
    pub at: i64,
    pub exe: String,
    pub app_name: String,
    pub idle: bool,
}

/// Active (non-idle) time of one app in a time range.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppUsage {
    pub exe: String,
    pub app_name: String,
    pub seconds: i64,
}

struct Open {
    id: i64,
    exe: String,
    idle: bool,
    last: i64,
}

pub struct Store {
    conn: Connection,
    open: Option<Open>,
}

impl Store {
    pub fn open(path: &Path) -> rusqlite::Result<Self> {
        if let Some(dir) = path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        Self::init(Connection::open(path)?)
    }

    #[cfg(test)]
    pub fn in_memory() -> rusqlite::Result<Self> {
        Self::init(Connection::open_in_memory()?)
    }

    fn init(conn: Connection) -> rusqlite::Result<Self> {
        conn.pragma_update_and_check(None, "journal_mode", "WAL", |_| Ok(()))?;
        conn.execute_batch(SCHEMA)?;
        Ok(Self { conn, open: None })
    }

    /// Adds one sample. The time since the previous sample goes to this sample's app
    /// (a switch happened somewhere in between; 5 s granularity is fine for a daily total).
    pub fn record(&mut self, sample: &Sample) -> rusqlite::Result<()> {
        let previous = self
            .open
            .as_ref()
            .filter(|o| sample.at >= o.last && sample.at - o.last <= MAX_GAP_SECS);
        if let Some(open) = previous {
            if open.exe == sample.exe && open.idle == sample.idle {
                let id = open.id;
                self.conn.execute(
                    "UPDATE screen_sessions SET ended_at = ?1 WHERE id = ?2",
                    params![sample.at, id],
                )?;
                if let Some(open) = self.open.as_mut() {
                    open.last = sample.at;
                }
                return Ok(());
            }
        }
        let started_at = previous.map_or(sample.at, |o| o.last);
        self.conn.execute(
            "INSERT INTO screen_sessions (exe, app_name, started_at, ended_at, idle)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                sample.exe,
                sample.app_name,
                started_at,
                sample.at,
                sample.idle
            ],
        )?;
        self.open = Some(Open {
            id: self.conn.last_insert_rowid(),
            exe: sample.exe.clone(),
            idle: sample.idle,
            last: sample.at,
        });
        Ok(())
    }

    /// Nothing usable on screen (locked, no foreground window): the next sample starts fresh.
    pub fn pause(&mut self) {
        self.open = None;
    }

    /// Active time per app in `[start, end)`, sessions clipped to the range, biggest first.
    /// Apps are grouped case-insensitively by exe name.
    pub fn usage(&self, start: i64, end: i64) -> rusqlite::Result<Vec<AppUsage>> {
        let mut stmt = self.conn.prepare_cached(
            "SELECT exe, app_name, total FROM (
                 SELECT lower(exe) AS key,
                        max(exe) AS exe,
                        max(app_name) AS app_name,
                        sum(min(ended_at, ?2) - max(started_at, ?1)) AS total
                 FROM screen_sessions
                 WHERE ended_at > ?1 AND started_at < ?2 AND idle = 0
                 GROUP BY key
             )
             WHERE total > 0
             ORDER BY total DESC, exe",
        )?;
        let rows = stmt.query_map(params![start, end], |row| {
            Ok(AppUsage {
                exe: row.get(0)?,
                app_name: row.get(1)?,
                seconds: row.get(2)?,
            })
        })?;
        rows.collect()
    }

    /// Records that a warning was shown; `false` if it already had been (today).
    pub fn mark_alert(
        &self,
        day: &str,
        limit_name: &str,
        level: u8,
        at: i64,
    ) -> rusqlite::Result<bool> {
        let inserted = self.conn.execute(
            "INSERT OR IGNORE INTO limit_alerts (day, limit_name, level, at) VALUES (?1, ?2, ?3, ?4)",
            params![day, limit_name, level, at],
        )?;
        Ok(inserted == 1)
    }

    /// Unix seconds of the last successful backend sync; 0 = never.
    pub fn synced_until(&self) -> rusqlite::Result<i64> {
        use rusqlite::OptionalExtension;
        Ok(self
            .conn
            .query_row(
                "SELECT value FROM sync_state WHERE key = 'synced_until'",
                [],
                |r| r.get(0),
            )
            .optional()?
            .unwrap_or(0))
    }

    pub fn set_synced_until(&self, at: i64) -> rusqlite::Result<()> {
        self.conn.execute(
            "INSERT INTO sync_state (key, value) VALUES ('synced_until', ?1)
             ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            params![at],
        )?;
        Ok(())
    }

    #[cfg(test)]
    fn sessions(&self) -> Vec<(String, i64, i64, bool)> {
        let mut stmt = self
            .conn
            .prepare("SELECT exe, started_at, ended_at, idle FROM screen_sessions ORDER BY id")
            .unwrap();
        stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))
            .unwrap()
            .collect::<rusqlite::Result<_>>()
            .unwrap()
    }

    #[cfg(test)]
    fn alert_at(&self, day: &str, name: &str, level: u8) -> Option<i64> {
        use rusqlite::OptionalExtension;
        self.conn
            .query_row(
                "SELECT at FROM limit_alerts WHERE day = ?1 AND limit_name = ?2 AND level = ?3",
                params![day, name, level],
                |r| r.get(0),
            )
            .optional()
            .unwrap()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(at: i64, exe: &str) -> Sample {
        Sample {
            at,
            exe: exe.into(),
            app_name: exe.trim_end_matches(".exe").into(),
            idle: false,
        }
    }

    #[test]
    fn same_app_extends_one_session() {
        let mut store = Store::in_memory().unwrap();
        for at in [100, 105, 110, 115] {
            store.record(&sample(at, "code.exe")).unwrap();
        }
        assert_eq!(store.sessions(), vec![("code.exe".into(), 100, 115, false)]);
    }

    #[test]
    fn switching_apps_hands_over_without_gaps_or_overlap() {
        let mut store = Store::in_memory().unwrap();
        store.record(&sample(100, "code.exe")).unwrap();
        store.record(&sample(105, "code.exe")).unwrap();
        store.record(&sample(110, "chrome.exe")).unwrap();
        store.record(&sample(115, "chrome.exe")).unwrap();
        assert_eq!(
            store.sessions(),
            vec![
                ("code.exe".into(), 100, 105, false),
                ("chrome.exe".into(), 105, 115, false),
            ]
        );
    }

    #[test]
    fn a_long_gap_is_not_counted() {
        let mut store = Store::in_memory().unwrap();
        store.record(&sample(100, "code.exe")).unwrap();
        store.record(&sample(105, "code.exe")).unwrap();
        store.record(&sample(3_700, "code.exe")).unwrap(); // laptop slept an hour
        store.record(&sample(3_705, "code.exe")).unwrap();
        let usage = store.usage(0, 10_000).unwrap();
        assert_eq!(usage[0].seconds, 10);
    }

    #[test]
    fn pause_starts_a_new_session() {
        let mut store = Store::in_memory().unwrap();
        store.record(&sample(100, "code.exe")).unwrap();
        store.pause();
        store.record(&sample(105, "code.exe")).unwrap();
        assert_eq!(store.sessions().len(), 2);
    }

    #[test]
    fn clock_going_backwards_starts_fresh() {
        let mut store = Store::in_memory().unwrap();
        store.record(&sample(100, "code.exe")).unwrap();
        store.record(&sample(90, "code.exe")).unwrap();
        assert_eq!(store.sessions().len(), 2);
    }

    #[test]
    fn usage_skips_idle_and_clips_to_the_range() {
        let mut store = Store::in_memory().unwrap();
        // 23:59:50 → 00:00:10 across "midnight" at 1000
        for at in [990, 995, 1000, 1005, 1010] {
            store.record(&sample(at, "valorant.exe")).unwrap();
        }
        store
            .record(&Sample {
                idle: true,
                ..sample(1015, "chrome.exe")
            })
            .unwrap();
        let today = store.usage(1000, 2000).unwrap();
        assert_eq!(
            today,
            vec![AppUsage {
                exe: "valorant.exe".into(),
                app_name: "valorant".into(),
                seconds: 10
            }]
        );
    }

    #[test]
    fn usage_groups_exe_names_case_insensitively() {
        let mut store = Store::in_memory().unwrap();
        store.record(&sample(100, "Code.exe")).unwrap();
        store.record(&sample(110, "Code.exe")).unwrap();
        store.pause();
        store.record(&sample(200, "code.EXE")).unwrap();
        store.record(&sample(205, "code.EXE")).unwrap();
        let usage = store.usage(0, 1000).unwrap();
        assert_eq!(usage.len(), 1);
        assert_eq!(usage[0].seconds, 15);
    }

    #[test]
    fn alerts_are_marked_once_per_day() {
        let store = Store::in_memory().unwrap();
        assert!(store.mark_alert("2026-11-20", "VALORANT", 80, 1).unwrap());
        assert!(!store.mark_alert("2026-11-20", "VALORANT", 80, 2).unwrap());
        assert!(store.mark_alert("2026-11-20", "VALORANT", 100, 3).unwrap());
        assert!(store.mark_alert("2026-11-21", "VALORANT", 80, 4).unwrap());
        assert_eq!(store.alert_at("2026-11-20", "VALORANT", 80), Some(1));
    }
}
