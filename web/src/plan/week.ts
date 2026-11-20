/** Pure helpers of the week view (tested in week.test.ts). Dates are ISO `YYYY-MM-DD`. */

const ISO = /^\d{4}-\d{2}-\d{2}$/;
const MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"];
const DAYS_SHORT = ["Paz", "Pzt", "Sal", "Çar", "Per", "Cum", "Cmt"]; // Date.getDay order

function parse(iso: string): Date {
  return new Date(`${iso}T12:00:00`); // noon: no DST edge
}

function format(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(iso: string, days: number): string {
  const date = parse(iso);
  date.setDate(date.getDate() + days);
  return format(date);
}

export function mondayOf(iso: string): string {
  const day = parse(iso).getDay(); // 0 = Sunday
  return addDays(iso, -((day + 6) % 7));
}

export function shiftWeek(monday: string, weeks: number): string {
  return addDays(monday, weeks * 7);
}

/** `?week=` from the URL: a valid date, moved to its Monday; anything else = this week. */
export function weekParam(value: string | null): string | null {
  if (!value || !ISO.test(value) || Number.isNaN(parse(value).getTime())) return null;
  return mondayOf(value);
}

/** "16–22 Kasım", "30 Kasım – 6 Aralık", "28 Aralık 2026 – 3 Ocak 2027". */
export function weekRange(monday: string): string {
  const start = parse(monday);
  const end = parse(addDays(monday, 6));
  const month = (d: Date): string => MONTHS[d.getMonth()] ?? "";
  if (start.getFullYear() !== end.getFullYear()) {
    return `${String(start.getDate())} ${month(start)} ${String(start.getFullYear())} – ${String(end.getDate())} ${month(end)} ${String(end.getFullYear())}`;
  }
  if (start.getMonth() !== end.getMonth()) {
    return `${String(start.getDate())} ${month(start)} – ${String(end.getDate())} ${month(end)}`;
  }
  return `${String(start.getDate())}–${String(end.getDate())} ${month(start)}`;
}

/** Where a moved class went: "Cum 20 Kas 14:00" (only the time when it stayed on the day). */
export function movedTo(target: string, day: string): string {
  const [date = "", time = ""] = target.split(" ");
  if (date === day) return time;
  const d = parse(date);
  return `${DAYS_SHORT[d.getDay()] ?? ""} ${String(d.getDate())} ${(MONTHS[d.getMonth()] ?? "").slice(0, 3)} ${time}`;
}

/** A horizontal swipe: -1 = to the previous week (finger moved right), 1 = next, 0 = none. */
export function swipeDirection(dx: number, dy: number, min = 60): -1 | 0 | 1 {
  if (Math.abs(dx) < min || Math.abs(dx) < Math.abs(dy) * 1.5) return 0;
  return dx > 0 ? -1 : 1;
}
