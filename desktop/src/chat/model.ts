// Pure helpers for the chat panel (no DOM, no Tauri): easy to unit test.
import type { ApiError, ChatResponse, Team, TeamMember } from "../api";
import { tr } from "../i18n/tr";

/** Same fallback palette idea as the web app: stable color per agent id. */
const PALETTE = ["#4f46e5", "#0891b2", "#db2777", "#ca8a04", "#16a34a", "#9333ea"];

export interface Speaker {
  name: string;
  color: string;
}

function hash(text: string): number {
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

export function fallbackColor(id: string): string {
  return PALETTE[hash(id) % PALETTE.length] ?? "#4f46e5";
}

export function members(team: Team | null): TeamMember[] {
  if (!team) return [];
  return [team.coordinator, ...team.agents, ...(team.onboarding ? [team.onboarding] : [])];
}

/** Name + label color of whoever answered; unknown ids still get a stable color. */
export function speakerOf(team: Team | null, reply: Pick<ChatResponse, "speaker" | "agents">): Speaker {
  const member = members(team).find((m) => m.id === reply.speaker);
  const fromReply = reply.agents.find((a) => a.agent_id === reply.speaker)?.name;
  return {
    name: member?.name ?? fromReply ?? tr.appName,
    color: member?.color ?? fallbackColor(reply.speaker),
  };
}

/** Agents that worked on the message besides the one who answered (delegations). */
export function helpers(team: Team | null, reply: Pick<ChatResponse, "speaker" | "agents">): Speaker[] {
  const seen = new Set<string>([reply.speaker]);
  const out: Speaker[] = [];
  for (const agent of reply.agents) {
    if (seen.has(agent.agent_id)) continue;
    seen.add(agent.agent_id);
    const member = members(team).find((m) => m.id === agent.agent_id);
    out.push({ name: member?.name ?? agent.name, color: member?.color ?? fallbackColor(agent.agent_id) });
  }
  return out;
}

function isApiError(value: unknown): value is ApiError {
  return typeof value === "object" && value !== null && typeof (value as ApiError).code === "string";
}

/** The server refused us for want of a (valid) device key - also a bare 401 ("http"),
 *  whatever the body said: the chat then shows the key screen, not a red error. */
export function needsKey(error: unknown): boolean {
  if (!isApiError(error)) return false;
  return error.code === "login_required" || error.code === "device_key_invalid" || (error.code === "http" && error.status === 401);
}

/** Rust command errors (`ApiError`) → one Turkish sentence. */
export function errorMessage(error: unknown): string {
  if (!isApiError(error)) return tr.errors.unknown;
  if (error.code === "http" && error.status === 401) return tr.errors.login_required;
  switch (error.code) {
    case "invalid_url":
    case "unreachable":
    case "timeout":
    case "bad_response":
    case "save_failed":
    case "login_required":
    case "wrong_password":
    case "too_many_attempts":
    case "device_key_invalid":
    case "invalid_key":
      return tr.errors[error.code];
    case "http":
      return tr.errors.http(error.status ?? 0);
    default:
      return tr.errors.unknown;
  }
}

export interface StoredConversation {
  get(): number | null;
  set(id: number | null): void;
}

/** The open conversation survives restarts; storage may be unavailable, so never throw. */
export function conversationStore(storage: Storage | undefined, key = "yaver.conversation_id"): StoredConversation {
  return {
    get() {
      try {
        const raw = storage?.getItem(key);
        const id = raw ? Number(raw) : NaN;
        return Number.isInteger(id) && id > 0 ? id : null;
      } catch {
        return null;
      }
    },
    set(id) {
      try {
        if (id === null) storage?.removeItem(key);
        else storage?.setItem(key, String(id));
      } catch {
        // per-viewer convenience only
      }
    },
  };
}
