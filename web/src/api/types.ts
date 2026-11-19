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
  user_name: string;
}

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

export interface DayPlan {
  date: string;
  weekday: string;
  items: PlanItem[];
  cancelled?: CancelledItem[];
  conflicts?: [string, string][];
  holidays?: string[];
  tasks?: PlanTask[];
  week_tasks?: PlanTask[];
}

export interface DayPlanResponse extends DayPlan {
  today: string;
}

export interface WeekPlanResponse {
  today: string;
  week_start: string;
  days: DayPlan[];
}

export interface CourseAttendance {
  course: string;
  name: string;
  absences: number;
  limit: number | null;
  remaining?: number;
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

export interface HistoryMessage {
  id: number;
  role: "user" | "assistant";
  agent_id: string | null;
  content: string;
  created_at: string;
  change_set_id: string | null;
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
  | DoneEvent
  | { type: "error"; code: string };
