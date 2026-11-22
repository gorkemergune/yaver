// GET /api/reports (backend/app/api/reports.py) and the date paging of the reports tab.
import { isoDate } from "../api/queries";

export interface EmployeeRow {
  id: string;
  name: string;
  requests: number;
  delegated: number;
  shift: number;
  failed: number;
  handoffs: number;
  tool_errors: number;
  cost_usd: string;
}

export interface RoutingRow {
  at: string;
  message_id: number;
  text: string;
  intents: [string, string | null][];
  speaker: string | null;
  helpers: string[];
  handoffs: number;
  errors: number;
  cost_usd: string | null;
}

export interface ProblemRow {
  at: string;
  kind: "failed" | "handoff";
  agent_id: string | null;
  text: string;
  reason: string;
  area?: string;
  in_words?: boolean;
}

export interface OfficeReport {
  period: "day" | "week";
  from: string;
  to: string;
  employees: EmployeeRow[];
  totals: Omit<EmployeeRow, "id" | "name">;
  routing: RoutingRow[];
  problems: ProblemRow[];
  bugs: {
    open: number;
    latest: { id: number; at: string; agent_id: string | null; note: string; text: string; source: string }[];
  };
}

/** Moves `date` (YYYY-MM-DD, local) by whole days. */
export function shiftDate(date: string, days: number): string {
  const [y, m, d] = date.split("-").map(Number);
  return isoDate(new Date(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + days));
}

