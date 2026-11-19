import type { PlanItem } from "../api/types";
import { tr } from "../i18n/tr";
import { shortDate } from "../lib/changes";

/** "09:00–11:00", "09:00" (a point in time), multi-day "28 Kas 09:00 – 29 Kas 18:00", or all day. */
export function timeRange(item: PlanItem): string {
  if (item.all_day) {
    if (item.starts_on && item.ends_on && item.starts_on !== item.ends_on) {
      return `${shortDate(item.starts_on)} – ${shortDate(item.ends_on)} · ${tr.plan.allDay}`;
    }
    return tr.plan.allDay;
  }
  const start = item.start ?? "";
  if (!item.end) return start;
  if (item.starts_on && item.ends_on && item.starts_on !== item.ends_on) {
    return `${shortDate(item.starts_on)} ${start} – ${shortDate(item.ends_on)} ${item.end}`;
  }
  return `${start}–${item.end}`;
}

/** Everything the card can show when opened: label + value pairs, in reading order. */
export function detailLines(item: PlanItem): { label: string; value: string }[] {
  const lines: { label: string; value: string }[] = [
    { label: tr.plan.detail.time, value: timeRange(item) },
    { label: tr.plan.detail.kind, value: tr.kinds[item.kind] ?? item.kind },
  ];
  if (item.location) lines.push({ label: tr.plan.detail.place, value: item.location });
  if (item.moved_from) lines.push({ label: tr.plan.detail.moved, value: tr.plan.moved(item.moved_from.slice(11)) });
  if (item.note) lines.push({ label: tr.plan.detail.note, value: item.note });
  return lines;
}
