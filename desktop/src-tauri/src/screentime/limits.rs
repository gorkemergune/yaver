//! Daily app limits from config.json. This step only warns (80 % and 100 %); closing the
//! process is deliberately not implemented yet.

use super::store::AppUsage;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AppLimit {
    /// Shown in warnings and the panel, e.g. "VALORANT".
    pub name: String,
    /// Exe names this limit covers (case-insensitive, `.exe` optional).
    pub processes: Vec<String>,
    pub daily_minutes: u32,
}

/// Warning levels, % of the limit.
pub const LEVELS: [u8; 2] = [80, 100];

fn normalize(exe: &str) -> String {
    let lower = exe.trim().to_lowercase();
    lower
        .strip_suffix(".exe")
        .map(str::to_owned)
        .unwrap_or(lower)
}

impl AppLimit {
    pub fn covers(&self, exe: &str) -> bool {
        let exe = normalize(exe);
        self.processes.iter().any(|p| normalize(p) == exe)
    }

    pub fn limit_seconds(&self) -> i64 {
        i64::from(self.daily_minutes) * 60
    }

    /// Today's active seconds of every covered app.
    pub fn used_seconds(&self, usage: &[AppUsage]) -> i64 {
        usage
            .iter()
            .filter(|u| self.covers(&u.exe))
            .map(|u| u.seconds)
            .sum()
    }

    /// Levels reached so far (ascending). A zero-minute limit is ignored (misconfigured).
    pub fn reached(&self, used_seconds: i64) -> Vec<u8> {
        let limit = self.limit_seconds();
        if limit <= 0 {
            return Vec::new();
        }
        LEVELS
            .into_iter()
            .filter(|level| used_seconds * 100 >= limit * i64::from(*level))
            .collect()
    }
}

pub fn any_covers(limits: &[AppLimit], exe: &str) -> bool {
    limits.iter().any(|l| l.covers(exe))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valorant() -> AppLimit {
        AppLimit {
            name: "VALORANT".into(),
            processes: vec!["VALORANT-Win64-Shipping.exe".into(), "VALORANT".into()],
            daily_minutes: 90,
        }
    }

    #[test]
    fn matches_exe_names_loosely() {
        let limit = valorant();
        assert!(limit.covers("valorant-win64-shipping.EXE"));
        assert!(limit.covers("VALORANT.exe"));
        assert!(!limit.covers("chrome.exe"));
    }

    #[test]
    fn sums_every_covered_process() {
        let usage = vec![
            AppUsage {
                exe: "VALORANT-Win64-Shipping.exe".into(),
                app_name: "VALORANT".into(),
                seconds: 3000,
            },
            AppUsage {
                exe: "VALORANT.exe".into(),
                app_name: "VALORANT".into(),
                seconds: 60,
            },
            AppUsage {
                exe: "chrome.exe".into(),
                app_name: "Google Chrome".into(),
                seconds: 9999,
            },
        ];
        assert_eq!(valorant().used_seconds(&usage), 3060);
    }

    #[test]
    fn levels_are_reached_at_80_and_100_percent() {
        let limit = valorant(); // 5400 s
        assert!(limit.reached(4319).is_empty());
        assert_eq!(limit.reached(4320), vec![80]);
        assert_eq!(limit.reached(5400), vec![80, 100]);
    }

    #[test]
    fn zero_minute_limit_never_fires() {
        let limit = AppLimit {
            daily_minutes: 0,
            ..valorant()
        };
        assert!(limit.reached(10_000).is_empty());
    }
}
