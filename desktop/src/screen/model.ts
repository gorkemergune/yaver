// Pure helpers for the screen-time view (no DOM, no Tauri).

export interface AppTime {
  exe: string;
  name: string;
  seconds: number;
}

export interface LimitTime {
  name: string;
  used_seconds: number;
  limit_seconds: number;
}

/** `screen_time_today` (src-tauri/src/screentime/mod.rs: Summary). */
export interface ScreenSummary {
  date: string;
  supported: boolean;
  tracking: boolean;
  total_seconds: number;
  apps: AppTime[];
  limits: LimitTime[];
  config_path: string;
  config_error: string | null;
}

/** Same format as the Rust warnings: `1 sa 12 dk`, `5 dk`, `0 dk`. */
export function fmtDuration(seconds: number): string {
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m} dk`;
  if (m === 0) return `${h} sa`;
  return `${h} sa ${m} dk`;
}

export type LimitState = "ok" | "warn" | "over";

/** Matches the warning levels: 80 % and 100 %. */
export function limitState(used: number, limit: number): LimitState {
  if (limit <= 0) return "ok";
  if (used >= limit) return "over";
  if (used * 100 >= limit * 80) return "warn";
  return "ok";
}

/** Share of the bar to fill, 0..1 (a limit can be exceeded; the bar stays full). */
export function fill(value: number, max: number): number {
  if (max <= 0) return 0;
  return Math.min(1, Math.max(0, value / max));
}

/** The biggest `max` apps, the rest summed into one "other" row. */
export function topApps(apps: AppTime[], max: number, otherName: string): AppTime[] {
  if (apps.length <= max) return apps;
  const shown = apps.slice(0, max - 1);
  const rest = apps.slice(max - 1).reduce((sum, app) => sum + app.seconds, 0);
  return [...shown, { exe: "", name: otherName, seconds: rest }];
}

/** `2026-11-20` → `20 Kasım Cuma` (date only, no time zone shifts). */
export function fmtDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  const date = new Date(Date.UTC(y, m - 1, d));
  return new Intl.DateTimeFormat("tr-TR", {
    day: "numeric",
    month: "long",
    weekday: "long",
    timeZone: "UTC",
  }).format(date);
}
