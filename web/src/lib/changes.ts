import type { Change } from "../api/types";
import { tr } from "../i18n/tr";

type Data = Change["data"];

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

export function hhmm(value: unknown): string {
  return text(value).slice(0, 5);
}

const weekday = (value: unknown): string =>
  typeof value === "number" ? (tr.weekdaysShort[value] ?? "") : "";

export function shortDate(iso: unknown): string {
  const value = text(iso);
  if (!value) return "";
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  return date.toLocaleDateString("tr-TR", { day: "numeric", month: "short", weekday: "short" });
}

function localTime(iso: unknown): string {
  const value = text(iso);
  if (!value) return "";
  return new Date(value).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
}

function blockLine(data: Data): string {
  const when = `${weekday(data.weekday)} ${hhmm(data.start_time)}–${hhmm(data.end_time)}`;
  return `${text(data.title)} (${when.trim()})`;
}

/** One Turkish line per change for the change card. */
export function describeChange(change: Change): string {
  const { entity, op, data } = change;
  const verb = { create: "eklendi", update: "güncellendi", delete: "silindi" }[op];
  switch (entity) {
    case "recurring_blocks":
      return `Haftalık ${tr.kinds[text(data.kind)]?.toLowerCase() ?? "blok"}: ${blockLine(data)} ${verb}`;
    case "block_overrides":
      if (data.action === "move") {
        return `${text(data.title)} ${shortDate(data.date)} → ${shortDate(data.new_start_at)} ${localTime(data.new_start_at)} taşındı`;
      }
      return `${text(data.title)} ${shortDate(data.date)} iptal edildi`;
    case "events": {
      const time = data.all_day ? tr.plan.allDay.toLowerCase() : localTime(data.start_at);
      return `${tr.kinds[text(data.kind)] ?? "Etkinlik"}: ${text(data.title)}, ${shortDate(data.start_at)} ${time} ${verb}`;
    }
    case "attendance": {
      const hours = typeof data.hours === "number" ? ` (${String(data.hours)} saat)` : "";
      const what = data.status === "absent" ? `devamsızlık${hours}` : text(data.status);
      return op === "delete"
        ? `${text(data.course)} ${shortDate(data.date)}: devamsızlık kaydı silindi`
        : `${text(data.course)} ${shortDate(data.date)}: ${what} kaydedildi`;
    }
    case "attendance_baselines":
      return `${text(data.course)}: Yaver öncesi devamsızlık ${text(data.hours)} saat`;
    case "courses":
      return op === "update" && data.absence_limit !== undefined
        ? `${text(data.code)} devamsızlık limiti: ${text(data.absence_limit)} saat`
        : `Ders: ${text(data.name) || text(data.code)} ${verb}`;
    case "tasks":
      return data.status === "done" ? `Görev tamamlandı: ${text(data.title)}` : `Görev: ${text(data.title)} ${verb}`;
    case "followups":
      return `Takip: ${text(data.title)} ${verb}`;
    case "week_labels":
      return op === "delete"
        ? `${shortDate(data.week_start)} haftasının adı kaldırıldı`
        : `${shortDate(data.week_start)} haftasının adı: ${text(data.label)}`;
    case "memories":
      return op === "update" ? `Unutuldu: ${text(data.content)}` : `Hatırlanacak: ${text(data.content)}`;
    default:
      return `${entity} ${verb}`;
  }
}

/** Courses created as a side effect of adding a class are noise on the card. */
export function visibleChanges(changes: Change[]): Change[] {
  const hasBlocks = changes.some((c) => c.entity === "recurring_blocks");
  return changes.filter((c) => !(hasBlocks && c.entity === "courses" && c.op === "create"));
}
