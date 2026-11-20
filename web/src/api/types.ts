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
  kind?: "briefing" | "checkin" | "followup" | "weekly_plan" | null; // written by the scheduler
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
  | DoneEvent
  | { type: "error"; code: string };
