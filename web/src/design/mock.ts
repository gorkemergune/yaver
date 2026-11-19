// Sample content for the design preview only (made-up data, like examples/).

export type Role = "coordinator" | "academic" | "agenda" | "discipline";

export interface PreviewMember {
  id: string;
  role: Role;
  name: string;
  color: string;
}

export const DEFAULT_MEMBERS: PreviewMember[] = [
  { id: "yaver", role: "coordinator", name: "Yaver", color: "#6366f1" },
  { id: "academic", role: "academic", name: "Friday", color: "#0ea5e9" },
  { id: "agenda", role: "agenda", name: "Jarvis", color: "#f59e0b" },
  { id: "discipline", role: "discipline", name: "Karen", color: "#10b981" },
];

export type ChatLine =
  | { kind: "user"; text: string }
  | { kind: "yaver"; member: Role; text: string; change?: string }
  | { kind: "typing"; member: Role };

export const CHAT: ChatLine[] = [
  { kind: "user", text: "Bugün linear iptal, yarın 14'te Iceberg toplantısı var" },
  { kind: "yaver", member: "academic", text: "bugünkü Linear Algebra dersini iptal etti.", change: "23 Kasım · Linear Algebra iptal" },
  { kind: "yaver", member: "agenda", text: "yarın 14:00'e Iceberg toplantısını ekledi.", change: "24 Kasım 14:00 · Iceberg toplantısı" },
  { kind: "yaver", member: "coordinator", text: "İkisi de tamam. Akşam sporun 19:00'da, unutma 💪" },
  { kind: "user", text: "Bu hafta devamsızlığım nasıl?" },
  { kind: "typing", member: "academic" },
];

export interface Block {
  start: string; // HH:MM
  end: string;
  title: string;
  place?: string;
  member: Role;
  cancelled?: boolean;
}

export const TODAY: Block[] = [
  { start: "09:00", end: "11:00", title: "Linear Algebra", place: "B204", member: "academic", cancelled: true },
  { start: "13:00", end: "15:00", title: "Fizik II", place: "A110", member: "academic" },
  { start: "15:30", end: "16:15", title: "Iceberg sync", place: "Online", member: "agenda" },
  { start: "19:00", end: "20:00", title: "Spor", place: "Kampüs spor salonu", member: "discipline" },
];

export const DAY_START_HOUR = 8;
export const DAY_END_HOUR = 21;
