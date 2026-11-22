// Shapes of the backend API (app/api/*.py).

export interface Member {
  id: string;
  name: string;
  color: string;
  domain: string;
}

export interface Team {
  coordinator: Member;
  agents: Member[];
  onboarding: Member | null;
  user_name: string;
  config_problems?: ConfigProblem[];
}

/** A configuration mistake the API survived (app/core/config_problems.py). */
export interface ConfigProblem {
  source: string; // ".env", "agents.yaml", "providers.yaml"
  field: string | null;
  message: string;
  fallback: string;
}

export interface OnboardingStatus {
  needed: boolean;
  open_conversation_id: number | null;
}

export type ChatMode = "chat" | "onboarding";

export interface PlanItem {
  type: "block" | "event";
  id: number;
  kind: string;
  title: string;
  start?: string;
  end?: string;
  all_day?: boolean;
  starts_on?: string;
  ends_on?: string;
  location?: string;
  moved_from?: string;
  note?: string;
}

export interface CancelledItem {
  block_id: number;
  title: string;
  start: string;
  reason: string | null;
}

export interface PlanTask {
  id: number;
  title: string;
  status: "todo" | "done" | "cancelled";
}

/** A missed class session (week view, past days). */
export interface DayAttendance {
  course: string;
  hours: number;
  status: "absent" | "excused";
  block_id: number | null;
}

/** An occurrence of this day moved to another time ("eski → yeni"). */
export interface MovedAway {
  block_id: number;
  title: string;
  start: string;
  moved_to: string; // "YYYY-MM-DD HH:MM"
  moved_to_end: string;
  reason: string | null;
}

export interface DayPlan {
  date: string;
  weekday: string;
  items: PlanItem[];
  cancelled?: CancelledItem[];
  moved_away?: MovedAway[];
  attendance?: DayAttendance[];
  conflicts?: [string, string][];
  holidays?: string[];
  tasks?: PlanTask[];
  week_tasks?: PlanTask[];
}

export interface DayPlanResponse extends DayPlan {
  today: string;
}

/** Term week facts (app/services/weeks.py). */
export interface WeekFacts {
  week_start: string;
  title: string | null; // "2026-27 Güz · 8. Hafta"; null outside a term
  term: string | null;
  week_no: number | null;
  label: string | null; // the user's name for the week, else the automatic one
  label_source: "user" | "auto" | null;
  auto_label: string | null;
  holidays: string[];
  exams: number;
  quizzes: number;
  absence_hours: number;
}

export interface WeekPlanResponse {
  today: string;
  week_start: string;
  week: WeekFacts;
  days: DayPlan[];
}

export interface StudySheetSummary {
  id: number;
  title: string;
  course: string | null;
  week: number | null;
  created_at: string;
  sources: number;
}

export interface StudySheet extends Omit<StudySheetSummary, "sources"> {
  content_md: string; // ends with "## Kaynaklar"
  model: string;
  sources: { n: number; title: string; pages: string; material_id: number }[];
}

export interface TermWeeks {
  term: { id: number; name: string; start_date: string; end_date: string } | null;
  current_week_start: string;
  weeks: WeekFacts[];
}

/** Absences in class hours (app/services/attendance.py). */
export interface CourseAttendance {
  course: string;
  name: string;
  absent_hours: number; // recorded + baseline
  recorded_hours: number;
  baseline?: { hours: number; note: string | null };
  limit_hours: number | null;
  remaining_hours?: number;
}

export interface MonthUsage {
  month: string;
  total_usd: string;
  budget: {
    provider: string;
    limit_usd: string;
    spent_usd: string;
    ratio: number | null;
    level: "ok" | "downgrade" | "limit";
  };
  /** Tiers with their own monthly limit (deep: Opus for the marked weekly jobs). */
  tier_budgets?: {
    tier: string;
    model: string;
    limit_usd: string;
    spent_usd: string;
    reached: boolean;
    over_limit: string;
  }[];
  by_model: {
    provider: string;
    model: string;
    tier: string;
    calls: number;
    errors: number;
    cost_usd: string;
  }[];
}

export interface Change {
  entity: string;
  op: "create" | "update" | "delete";
  agent_id: string | null;
  data: Record<string, string | number | boolean | null>;
  undone: boolean;
}

export interface Attachment {
  id: number;
  url: string;
  mime: string; // image/jpeg ... or application/pdf (width = height = 0)
  width: number;
  height: number;
  filename?: string | null;
}

export interface HistoryMessage {
  id: number;
  role: "user" | "assistant";
  agent_id: string | null;
  content: string;
  created_at: string;
  change_set_id: string | null;
  attachments?: Attachment[];
  kind?: "briefing" | "checkin" | "followup" | "weekly_plan" | "exam_prep" | "day_report" | "meeting_prep" | null; // written by the scheduler
}

export interface HistoryResponse {
  conversation_id: number;
  messages: HistoryMessage[];
  change_sets: Record<string, { changes: Change[]; undone: boolean }>;
}

// --- streaming chat events (app/agent/loop.py, app/api/chat.py) -----------------------

export interface DoneEvent {
  type: "done";
  conversation_id: number;
  reply: string;
  speaker: string;
  change_set_id: string | null;
  agents: { agent_id: string; name: string; reply: string }[];
  changes: Change[];
  cost_usd: string;
  message_id?: number | null; // the stored answer (👎 "Hatalı" points at it)
}

export type ChatEvent =
  | { type: "turn"; agent_id: string }
  | { type: "text"; agent_id: string; delta: string }
  | { type: "reset"; agent_id: string }
  | {
      type: "tool";
      agent_id: string;
      tool: string;
      arguments: Record<string, unknown> | null;
      error: string | null;
      mutates: boolean;
    }
  | { type: "delegate"; agent_id: string; name: string; instruction: string }
  | { type: "agent_reply"; agent_id: string; name: string; reply: string }
  | { type: "status"; agent_id: string; code: "rate_limited"; provider: string; seconds: number }
  | { type: "status"; agent_id: string; code: "reading_images"; count: number }
  | { type: "ping" } // keep-alive while an answer is slow (api/chat.ts drops it)
  | DoneEvent
  | { type: "error"; code: string };

// --- the office (app/api/office.py, app/api/employees.py) ------------------------------

export type Activity = "working" | "meeting" | "break" | "off";

export interface EmployeeState {
  employee_id: string;
  activity: Activity;
  task: string | null;
  tool: string | null;
  meeting_with: string | null;
  needs_user: boolean;
  needs_user_reason: "question" | "budget" | null;
  since: string;
  ts: string;
}

export interface OfficeEmployee extends EmployeeState {
  id: string;
  name: string;
  role: string;
  color: string;
  desk: { row: "office" | "back" | "front"; col: number };
  is_coordinator: boolean;
  domain: string;
  shift: string;
  daily_budget_usd: number | null;
  spent_today_usd: number;
}

/** Office hours (agents.yaml office.open_at / close_at); off_hours: closed right now. */
export interface OfficeHours {
  open_at: string;
  close_at: string;
  off_hours: boolean;
}

export interface OfficeSnapshot {
  ready: boolean;
  employees: OfficeEmployee[];
  hours?: OfficeHours; // missing when the office is not ready
  ts: string;
}

export interface EmployeeNote {
  id: number;
  content: string;
  source?: string;
  created_at: string | null;
}

export type OfficeEvent =
  | ({ type: "snapshot" } & OfficeSnapshot)
  | ({ type: "state" } & EmployeeState)
  | { type: "note"; employee_id: string; note: EmployeeNote; ts: string }
  | ({ type: "hours"; ts: string } & OfficeHours)
  | { type: "ping"; ts: string };

export interface EmployeeTask {
  id: number;
  source: "user" | "yaver" | "shift";
  requested_by: string | null;
  instruction: string;
  status: "running" | "done" | "failed";
  result: string | null;
  conversation_id: number | null;
  change_set_id: string | null;
  tools: string[];
  started_at: string | null;
  finished_at: string | null;
}

export type BoardColumn = "waiting" | "running" | "approval" | "done";

export interface BoardCard {
  id: string;
  column: BoardColumn;
  employee_id: string;
  title: string;
  source: "user" | "yaver" | "shift";
  requested_by?: string | null;
  status: "scheduled" | "running" | "done" | "failed";
  result?: string | null;
  at: string;
}

export interface BoardResponse {
  columns: BoardColumn[];
  cards: BoardCard[];
  ts: string;
}

export interface DeviceKeyView {
  id: number;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}
