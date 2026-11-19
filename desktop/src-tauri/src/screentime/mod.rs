//! Screen time: samples the foreground app every 5 s into a local SQLite file, sums up
//! the day per app and warns when an app limit reaches 80 % / 100 %. Local only for now.

pub mod foreground;
pub mod limits;
pub mod store;

use crate::{notice, AppState};
use chrono::{DateTime, Local, NaiveTime, TimeZone};
use serde::Serialize;
use std::collections::HashMap;
use std::path::Path;
use std::sync::Mutex;
use std::time::Duration;
use store::{AppUsage, Sample, Store};
use tauri::{AppHandle, Manager};

pub const SAMPLE_INTERVAL: Duration = Duration::from_secs(5);
/// Hand edits to config.json (limits) are picked up this often.
const CONFIG_RELOAD_EVERY: u32 = 12; // samples = 1 min
pub const DB_FILE: &str = "screen_time.sqlite3";

/// User-facing warning texts (Turkish).
mod tr {
    use super::fmt_duration;

    pub fn warning_title(name: &str) -> String {
        format!("{name}: sınırın %80'i doldu")
    }

    pub fn limit_title(name: &str) -> String {
        format!("{name}: günlük sınır doldu")
    }

    pub fn warning_body(used: i64, limit: i64) -> String {
        format!(
            "Bugün {} kullandın, günlük sınır {}. Kalan: {}.",
            fmt_duration(used),
            fmt_duration(limit),
            fmt_duration((limit - used).max(0))
        )
    }

    pub fn limit_body(used: i64, limit: i64) -> String {
        format!(
            "Bugün {} kullandın (sınır {}). Bugünlük bu kadar olsa iyi olur.",
            fmt_duration(used),
            fmt_duration(limit)
        )
    }
}

/// `4320` → `1 sa 12 dk`, `300` → `5 dk`, `30` → `0 dk`.
pub fn fmt_duration(seconds: i64) -> String {
    let minutes = seconds.max(0) / 60;
    match (minutes / 60, minutes % 60) {
        (0, m) => format!("{m} dk"),
        (h, 0) => format!("{h} sa"),
        (h, m) => format!("{h} sa {m} dk"),
    }
}

pub struct ScreenTime {
    store: Mutex<Store>,
    /// exe path → display name; reading version resources every 5 s would be wasteful.
    names: Mutex<HashMap<String, String>>,
}

impl ScreenTime {
    pub fn open(data_dir: &Path) -> rusqlite::Result<Self> {
        Ok(Self {
            store: Mutex::new(Store::open(&data_dir.join(DB_FILE))?),
            names: Mutex::new(HashMap::new()),
        })
    }

    fn display_name(&self, app: &foreground::Foreground) -> String {
        let stem = || foreground::exe_stem(&app.exe).to_owned();
        let Some(path) = &app.path else {
            return stem();
        };
        let mut names = self.names.lock().expect("names lock");
        names
            .entry(path.clone())
            .or_insert_with(|| foreground::app_description(path).unwrap_or_else(stem))
            .clone()
    }
}

/// Local calendar day containing `now`: (start, end) as UTC unix seconds + `YYYY-MM-DD`.
pub fn local_day<Tz: TimeZone>(now: &DateTime<Tz>) -> (i64, i64, String) {
    let tz = now.timezone();
    let date = now.date_naive();
    let start_of = |day: chrono::NaiveDate| {
        let midnight = day.and_time(NaiveTime::MIN);
        // `earliest`: a DST jump at midnight still gives a valid instant.
        tz.from_local_datetime(&midnight)
            .earliest()
            .map_or_else(|| now.timestamp(), |t| t.timestamp())
    };
    let next = date.succ_opt().unwrap_or(date);
    (
        start_of(date),
        start_of(next),
        date.format("%Y-%m-%d").to_string(),
    )
}

/// Starts the sampler thread (Windows only; elsewhere screen time just stays empty).
pub fn start(app: AppHandle) {
    if !cfg!(windows) {
        log::info!("screen time: foreground sampling is Windows-only for now");
        return;
    }
    std::thread::Builder::new()
        .name("screen-time".into())
        .spawn(move || {
            let mut ticks: u32 = 0;
            loop {
                std::thread::sleep(SAMPLE_INTERVAL);
                ticks = ticks.wrapping_add(1);
                if ticks % CONFIG_RELOAD_EVERY == 0 {
                    app.state::<AppState>().reload_config();
                }
                if let Err(err) = tick(&app) {
                    log::warn!("screen time sample failed: {err}");
                }
            }
        })
        .expect("screen time thread");
}

fn tick(app: &AppHandle) -> rusqlite::Result<()> {
    let Some(screen) = app.try_state::<ScreenTime>() else {
        return Ok(());
    };
    let config = app.state::<AppState>().config();
    let Some(current) = foreground::current().filter(|_| config.track_screen_time) else {
        screen.store.lock().expect("store lock").pause();
        return Ok(());
    };
    let limited = limits::any_covers(&config.app_limits, &current.exe);
    let idle_after = u64::from(config.idle_minutes.max(1)) * 60;
    let idle = !limited && foreground::idle_seconds().is_some_and(|s| s >= idle_after);
    let now = Local::now();
    let sample = Sample {
        at: now.timestamp(),
        app_name: screen.display_name(&current),
        exe: current.exe,
        idle,
    };
    let notices = {
        let mut store = screen.store.lock().expect("store lock");
        store.record(&sample)?;
        // Only a limited app in the foreground can push its total up.
        if limited {
            due_warnings(&store, &config.app_limits, &sample.exe, &now)?
        } else {
            Vec::new()
        }
    };
    for warning in notices {
        log::info!("limit warning: {}", warning.title);
        notice::show(app, warning);
    }
    Ok(())
}

/// Warnings to show now; each level is marked in the DB so it fires once a day.
fn due_warnings<Tz: TimeZone>(
    store: &Store,
    app_limits: &[limits::AppLimit],
    exe: &str,
    now: &DateTime<Tz>,
) -> rusqlite::Result<Vec<notice::Notice>> {
    let (start, end, day) = local_day(now);
    let usage = store.usage(start, end)?;
    let mut out = Vec::new();
    for limit in app_limits.iter().filter(|l| l.covers(exe)) {
        let used = limit.used_seconds(&usage);
        let mut newest = None;
        for level in limit.reached(used) {
            if store.mark_alert(&day, &limit.name, level, now.timestamp())? {
                newest = Some(level);
            }
        }
        // Starting the app already over the limit shows only the 100 % one.
        let total = limit.limit_seconds();
        let shown = match newest {
            Some(100) => Some((tr::limit_title(&limit.name), tr::limit_body(used, total))),
            Some(_) => Some((
                tr::warning_title(&limit.name),
                tr::warning_body(used, total),
            )),
            None => None,
        };
        if let Some((title, body)) = shown {
            out.push(notice::Notice { title, body });
        }
    }
    Ok(out)
}

#[derive(Debug, Serialize)]
pub struct AppView {
    pub exe: String,
    pub name: String,
    pub seconds: i64,
}

#[derive(Debug, Serialize)]
pub struct LimitView {
    pub name: String,
    pub used_seconds: i64,
    pub limit_seconds: i64,
}

#[derive(Debug, Serialize)]
pub struct Summary {
    pub date: String,
    /// Sampling runs on this OS (Windows).
    pub supported: bool,
    /// `track_screen_time` in config.json.
    pub tracking: bool,
    pub total_seconds: i64,
    pub apps: Vec<AppView>,
    pub limits: Vec<LimitView>,
    pub config_path: String,
    /// config.json could not be read (the last good settings stay in use).
    pub config_error: Option<String>,
}

pub fn summarize(
    usage: &[AppUsage],
    app_limits: &[limits::AppLimit],
) -> (i64, Vec<AppView>, Vec<LimitView>) {
    let total = usage.iter().map(|u| u.seconds).sum();
    let apps = usage
        .iter()
        .map(|u| AppView {
            exe: u.exe.clone(),
            name: u.app_name.clone(),
            seconds: u.seconds,
        })
        .collect();
    let limit_views = app_limits
        .iter()
        .map(|l| LimitView {
            name: l.name.clone(),
            used_seconds: l.used_seconds(usage),
            limit_seconds: l.limit_seconds(),
        })
        .collect();
    (total, apps, limit_views)
}

#[tauri::command]
pub fn screen_time_today(app: AppHandle) -> Result<Summary, String> {
    let state = app.state::<AppState>();
    let config = state.config();
    let (start, end, date) = local_day(&Local::now());
    let usage = match app.try_state::<ScreenTime>() {
        Some(screen) => screen
            .store
            .lock()
            .expect("store lock")
            .usage(start, end)
            .map_err(|e| e.to_string())?,
        None => Vec::new(),
    };
    let (total_seconds, apps, limits) = summarize(&usage, &config.app_limits);
    Ok(Summary {
        date,
        supported: cfg!(windows) && app.try_state::<ScreenTime>().is_some(),
        tracking: config.track_screen_time,
        total_seconds,
        apps,
        limits,
        config_path: state.config_path().to_string_lossy().into_owned(),
        config_error: state.config_error(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{FixedOffset, Utc};

    #[test]
    fn formats_durations() {
        assert_eq!(fmt_duration(30), "0 dk");
        assert_eq!(fmt_duration(300), "5 dk");
        assert_eq!(fmt_duration(3600), "1 sa");
        assert_eq!(fmt_duration(4320), "1 sa 12 dk");
        assert_eq!(fmt_duration(-5), "0 dk");
    }

    #[test]
    fn local_day_follows_the_given_timezone() {
        let istanbul = FixedOffset::east_opt(3 * 3600).unwrap();
        // 2026-11-20 01:30 in Istanbul = 2026-11-19 22:30 UTC
        let now = istanbul.with_ymd_and_hms(2026, 11, 20, 1, 30, 0).unwrap();
        let (start, end, day) = local_day(&now);
        assert_eq!(day, "2026-11-20");
        assert_eq!(
            start,
            Utc.with_ymd_and_hms(2026, 11, 19, 21, 0, 0)
                .unwrap()
                .timestamp()
        );
        assert_eq!(end - start, 86_400);
    }

    #[test]
    fn summary_totals_and_limits() {
        let usage = vec![
            AppUsage {
                exe: "VALORANT-Win64-Shipping.exe".into(),
                app_name: "VALORANT".into(),
                seconds: 3600,
            },
            AppUsage {
                exe: "Code.exe".into(),
                app_name: "Visual Studio Code".into(),
                seconds: 1200,
            },
        ];
        let app_limits = vec![limits::AppLimit {
            name: "VALORANT".into(),
            processes: vec!["valorant-win64-shipping".into()],
            daily_minutes: 90,
        }];
        let (total, apps, limit_views) = summarize(&usage, &app_limits);
        assert_eq!(total, 4800);
        assert_eq!(apps[1].name, "Visual Studio Code");
        assert_eq!(limit_views[0].used_seconds, 3600);
        assert_eq!(limit_views[0].limit_seconds, 5400);
    }

    #[test]
    fn warnings_fire_once_per_level_and_day() {
        let istanbul = FixedOffset::east_opt(3 * 3600).unwrap();
        let now = istanbul.with_ymd_and_hms(2026, 11, 20, 20, 0, 0).unwrap();
        let app_limits = vec![limits::AppLimit {
            name: "VALORANT".into(),
            processes: vec!["valorant.exe".into()],
            daily_minutes: 1,
        }];
        let mut store = Store::in_memory().unwrap();
        let record = |store: &mut Store, at: i64| {
            store
                .record(&Sample {
                    at,
                    exe: "VALORANT.exe".into(),
                    app_name: "VALORANT".into(),
                    idle: false,
                })
                .unwrap();
        };
        let t0 = now.timestamp() - 60;
        record(&mut store, t0);
        record(&mut store, t0 + 10);
        assert!(due_warnings(&store, &app_limits, "VALORANT.exe", &now)
            .unwrap()
            .is_empty());
        for at in (t0 + 15..=t0 + 50).step_by(5) {
            record(&mut store, at); // 50 s of 60 = 83 %
        }
        let first = due_warnings(&store, &app_limits, "VALORANT.exe", &now).unwrap();
        assert_eq!(first.len(), 1);
        assert!(first[0].title.contains("%80"));
        assert!(due_warnings(&store, &app_limits, "VALORANT.exe", &now)
            .unwrap()
            .is_empty());
        record(&mut store, t0 + 55);
        record(&mut store, t0 + 60);
        let second = due_warnings(&store, &app_limits, "VALORANT.exe", &now).unwrap();
        assert_eq!(second.len(), 1);
        assert!(second[0].title.contains("günlük sınır doldu"));
        // another app in front doesn't trigger anything
        assert!(due_warnings(&store, &app_limits, "chrome.exe", &now)
            .unwrap()
            .is_empty());
    }

    #[test]
    fn warning_texts_mention_the_numbers() {
        assert_eq!(
            tr::warning_body(4320, 5400),
            "Bugün 1 sa 12 dk kullandın, günlük sınır 1 sa 30 dk. Kalan: 18 dk."
        );
        assert!(tr::limit_title("VALORANT").contains("günlük sınır doldu"));
    }
}
