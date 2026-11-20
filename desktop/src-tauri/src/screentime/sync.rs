//! Sends daily screen-time summaries to the backend (`POST /api/screen-time`).
//!
//! The local SQLite file is the buffer: nothing is queued separately. Each sync sends
//! every local day touched since the last successful sync, as a whole day (the backend
//! replaces it), so a lost response or a sync after a week offline is harmless.

use super::store::Store;
use super::{local_day, summarize, ScreenTime};
use crate::config::Config;
use crate::AppState;
use chrono::{DateTime, Duration as Days, Local, TimeZone};
use serde_json::{json, Value};
use std::time::Duration;
use tauri::{AppHandle, Manager};

pub const SYNC_EVERY: Duration = Duration::from_secs(10 * 60);
/// First sync shortly after start (yesterday's last minutes, a week offline...).
pub const FIRST_SYNC_AFTER: Duration = Duration::from_secs(30);
/// Never synced (or a very old mark): this many days back at most.
pub const MAX_DAYS_BACK: i64 = 14;
const FIRST_RUN_DAYS: i64 = 7;
/// Session rows are extended for up to this long after their day's last sample.
const SLACK_SECS: i64 = 60;

/// Local days to send: from the day of the last successful sync to today (oldest first).
pub fn days_to_send<Tz: TimeZone>(
    synced_until: i64,
    now: &DateTime<Tz>,
) -> Vec<(i64, i64, String)> {
    let today = now.date_naive();
    let from = if synced_until <= 0 {
        today - Days::days(FIRST_RUN_DAYS - 1)
    } else {
        let mark = now
            .timezone()
            .timestamp_opt(synced_until - SLACK_SECS, 0)
            .single()
            .map_or(today, |t| t.date_naive());
        mark.max(today - Days::days(MAX_DAYS_BACK - 1)).min(today)
    };
    let mut days = Vec::new();
    let mut day = from;
    while day <= today {
        let noon = day.and_hms_opt(12, 0, 0).expect("noon");
        if let Some(at) = now.timezone().from_local_datetime(&noon).earliest() {
            days.push(local_day(&at));
        }
        day = day.succ_opt().expect("next day");
    }
    days
}

/// Request body for the days (empty past days are left out; today always goes).
pub fn payload(
    store: &Store,
    config: &Config,
    device: &str,
    days: &[(i64, i64, String)],
) -> rusqlite::Result<Option<Value>> {
    let mut out = Vec::new();
    for (index, (start, end, date)) in days.iter().enumerate() {
        let usage = store.usage(*start, *end)?;
        let is_today = index + 1 == days.len();
        if usage.is_empty() && !is_today {
            continue;
        }
        let (total, apps, limits) = summarize(&usage, &config.app_limits);
        out.push(json!({
            "date": date,
            "total_seconds": total,
            "apps": apps.iter().map(|a| json!({"exe": a.exe, "name": a.name, "seconds": a.seconds})).collect::<Vec<_>>(),
            "limits": limits.iter().map(|l| json!({"name": l.name, "used_seconds": l.used_seconds, "limit_seconds": l.limit_seconds})).collect::<Vec<_>>(),
        }));
    }
    Ok((!out.is_empty()).then(|| json!({ "device": device, "days": out })))
}

/// The computer's name, so two PCs don't overwrite each other's days.
pub fn device_name() -> String {
    ["COMPUTERNAME", "HOSTNAME"]
        .iter()
        .find_map(|key| std::env::var(key).ok().filter(|v| !v.trim().is_empty()))
        .map_or_else(
            || "pc".to_owned(),
            |name| name.trim().chars().take(100).collect(),
        )
}

/// One sync; `Ok(n)` = days sent. Errors are logged by the caller and retried next time.
pub async fn sync_now(app: &AppHandle) -> Result<usize, String> {
    let Some(screen) = app.try_state::<ScreenTime>() else {
        return Ok(0);
    };
    let state = app.state::<AppState>();
    let config = state.config();
    if !config.track_screen_time {
        return Ok(0);
    }
    let now = Local::now();
    let body = {
        let store = screen.store.lock().expect("store lock");
        let synced_until = store.synced_until().map_err(|e| e.to_string())?;
        let days = days_to_send(synced_until, &now);
        payload(&store, &config, &device_name(), &days).map_err(|e| e.to_string())?
    };
    let Some(body) = body else {
        return Ok(0);
    };
    let count = body["days"].as_array().map_or(0, Vec::len);
    state
        .send_screen_time(&body)
        .await
        .map_err(|e| format!("{}: {}", e.code, e.detail.unwrap_or_default()))?;
    // Data recorded after `now` goes out next time (the day is resent as a whole).
    screen
        .store
        .lock()
        .expect("store lock")
        .set_synced_until(now.timestamp())
        .map_err(|e| e.to_string())?;
    Ok(count)
}

/// Every 10 minutes while the app runs.
pub fn start(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(FIRST_SYNC_AFTER).await;
        loop {
            match sync_now(&app).await {
                Ok(0) => {}
                Ok(days) => log::info!("screen time sent ({days} day(s))"),
                Err(err) => log::info!("screen time not sent, will retry: {err}"),
            }
            tokio::time::sleep(SYNC_EVERY).await;
        }
    });
}

/// On exit: one last try, a few seconds at most (the app must not hang on quit).
pub fn final_sync(app: &AppHandle) {
    let app = app.clone();
    let result = tauri::async_runtime::block_on(async move {
        tokio::time::timeout(Duration::from_secs(4), sync_now(&app)).await
    });
    match result {
        Ok(Ok(days)) => log::info!("screen time sent on exit ({days} day(s))"),
        Ok(Err(err)) => log::info!("screen time not sent on exit: {err}"),
        Err(_) => log::info!("screen time not sent on exit: timeout"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::screentime::limits::AppLimit;
    use crate::screentime::store::Sample;
    use chrono::FixedOffset;

    fn istanbul() -> FixedOffset {
        FixedOffset::east_opt(3 * 3600).unwrap()
    }

    #[test]
    fn days_since_the_last_sync() {
        let now = istanbul().with_ymd_and_hms(2026, 11, 20, 21, 0, 0).unwrap();
        let names =
            |days: Vec<(i64, i64, String)>| days.into_iter().map(|d| d.2).collect::<Vec<_>>();
        // synced 10 minutes ago: today only
        assert_eq!(
            names(days_to_send(now.timestamp() - 600, &now)),
            ["2026-11-20"]
        );
        // last sync yesterday evening (backend was down): yesterday and today
        let yesterday = istanbul()
            .with_ymd_and_hms(2026, 11, 19, 23, 50, 0)
            .unwrap();
        assert_eq!(
            names(days_to_send(yesterday.timestamp(), &now)),
            ["2026-11-19", "2026-11-20"]
        );
        // just after midnight: the sync at 00:00:30 still resends yesterday's last minute
        let midnight = istanbul().with_ymd_and_hms(2026, 11, 20, 0, 0, 30).unwrap();
        assert_eq!(days_to_send(midnight.timestamp(), &now)[0].2, "2026-11-19");
        // never synced: a week; a month offline: two weeks at most
        assert_eq!(days_to_send(0, &now).len(), 7);
        assert_eq!(days_to_send(now.timestamp() - 30 * 86_400, &now).len(), 14);
    }

    #[test]
    fn payload_skips_empty_past_days() {
        let now = istanbul().with_ymd_and_hms(2026, 11, 20, 21, 0, 0).unwrap();
        let mut store = Store::in_memory().unwrap();
        for at in (0..=600).step_by(5) {
            store
                .record(&Sample {
                    at: now.timestamp() - 3600 + at,
                    exe: "VALORANT.exe".into(),
                    app_name: "VALORANT".into(),
                    idle: false,
                })
                .unwrap();
        }
        let config = Config {
            app_limits: vec![AppLimit {
                name: "VALORANT".into(),
                processes: vec!["valorant.exe".into()],
                daily_minutes: 90,
            }],
            ..Config::default()
        };
        let days = days_to_send(now.timestamp() - 3 * 86_400, &now);
        assert_eq!(days.len(), 4);
        let body = payload(&store, &config, "PC", &days).unwrap().unwrap();
        assert_eq!(body["device"], "PC");
        let sent = body["days"].as_array().unwrap();
        assert_eq!(sent.len(), 1, "only today has data");
        assert_eq!(sent[0]["date"], "2026-11-20");
        assert_eq!(sent[0]["total_seconds"], 600);
        assert_eq!(sent[0]["apps"][0]["name"], "VALORANT");
        assert_eq!(sent[0]["limits"][0]["limit_seconds"], 5400);
        // an empty today is still sent (the backend then knows the app is alive)
        let empty = Store::in_memory().unwrap();
        let body = payload(&empty, &config, "PC", &days).unwrap().unwrap();
        assert_eq!(body["days"][0]["total_seconds"], 0);
    }

    #[test]
    fn sync_mark_is_stored() {
        let store = Store::in_memory().unwrap();
        assert_eq!(store.synced_until().unwrap(), 0);
        store.set_synced_until(1_800_000_000).unwrap();
        assert_eq!(store.synced_until().unwrap(), 1_800_000_000);
    }
}
