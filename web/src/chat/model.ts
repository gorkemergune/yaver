import type { Change, ChatEvent, HistoryResponse } from "../api/types";

export interface ToolStep {
  tool: string;
  error: string | null;
  mutates: boolean;
}

/** What one yaver did for a message (shown collapsed: "Friday 2 değişiklik yaptı ▸"). */
export interface AgentSteps {
  agentId: string;
  name: string;
  instruction?: string;
  tools: ToolStep[];
  reply?: string;
}

export interface UserItem {
  kind: "user";
  id: string;
  text: string;
  images: { url: string; name: string; mime?: string }[];
}

export type StatusLine = { code: "rate_limited"; provider: string } | { code: "reading_images"; count: number };

export interface AssistantItem {
  kind: "assistant";
  id: string;
  speaker: string | null; // agent id that answers; null until known
  text: string;
  streaming: boolean;
  steps: AgentSteps[];
  changeSetId: string | null;
  changes: Change[];
  undone: boolean;
  error: string | null;
  status: StatusLine | null; // waiting on Groq, reading images
  origin: "briefing" | "checkin" | "followup" | "weekly_plan" | "exam_prep" | null; // a message Yaver wrote on its own
}

export type ChatItem = UserItem | AssistantItem;

export function pendingAssistant(id: string): AssistantItem {
  return {
    kind: "assistant",
    id,
    speaker: null,
    text: "",
    streaming: true,
    steps: [],
    changeSetId: null,
    changes: [],
    undone: false,
    error: null,
    status: null,
    origin: null,
  };
}

function stepsFor(item: AssistantItem, agentId: string, name: string): [AgentSteps[], AgentSteps] {
  const existing = item.steps.find((s) => s.agentId === agentId);
  if (existing) return [item.steps, existing];
  const created: AgentSteps = { agentId, name, tools: [] };
  return [[...item.steps, created], created];
}

/**
 * Apply one streaming event to the pending answer. `names` maps agent ids to display names.
 * Only the speaker streams text; a new turn or a retry of the speaker clears the draft.
 */
export function applyEvent(
  item: AssistantItem,
  event: ChatEvent,
  names: Record<string, string>,
): AssistantItem {
  if (event.type === "status") {
    const status: StatusLine =
      event.code === "reading_images"
        ? { code: "reading_images", count: event.count }
        : { code: "rate_limited", provider: event.provider };
    return { ...item, status };
  }
  // Any progress after a wait clears the "waiting" line (a new turn alone doesn't).
  if (item.status && event.type !== "turn") item = { ...item, status: null };
  switch (event.type) {
    case "text":
      if (item.speaker !== event.agent_id) {
        return { ...item, speaker: event.agent_id, text: event.delta };
      }
      return { ...item, text: item.text + event.delta };
    case "turn":
    case "reset":
      return item.speaker === event.agent_id ? { ...item, text: "" } : item;
    case "delegate": {
      const [steps, step] = stepsFor(item, event.agent_id, event.name);
      return { ...item, steps: replace(steps, step, { ...step, instruction: event.instruction }) };
    }
    case "tool": {
      if (event.tool === "delegate") return item;
      const [steps, step] = stepsFor(item, event.agent_id, names[event.agent_id] ?? event.agent_id);
      const tools = [...step.tools, { tool: event.tool, error: event.error, mutates: event.mutates }];
      return { ...item, steps: replace(steps, step, { ...step, tools }) };
    }
    case "agent_reply": {
      const [steps, step] = stepsFor(item, event.agent_id, event.name);
      return { ...item, steps: replace(steps, step, { ...step, reply: event.reply }) };
    }
    case "done":
      return {
        ...item,
        speaker: event.speaker,
        text: event.reply,
        streaming: false,
        changeSetId: event.change_set_id,
        changes: event.changes,
      };
    case "error":
      return { ...item, streaming: false, error: event.code };
  }
}

function replace(steps: AgentSteps[], old: AgentSteps, next: AgentSteps): AgentSteps[] {
  return steps.map((s) => (s === old ? next : s));
}

/** Summary for a collapsed step row. */
export function stepSummary(step: AgentSteps): { kind: "changed" | "looked" | "asked"; count: number } {
  const count = step.tools.filter((t) => t.mutates && !t.error).length;
  if (count > 0) return { kind: "changed", count };
  if (step.reply?.trim().endsWith("?")) return { kind: "asked", count: 0 };
  return { kind: "looked", count: 0 };
}

/**
 * Stored history -> chat items. Messages between two user turns: earlier assistant
 * messages are yaver replies (steps), the last one is the answer.
 */
export function historyToItems(history: HistoryResponse, names: Record<string, string>): ChatItem[] {
  const items: ChatItem[] = [];
  let group: HistoryResponse["messages"] = [];

  const flush = (): void => {
    if (group.length === 0) return;
    const final = group[group.length - 1];
    if (!final) return;
    const set = final.change_set_id ? history.change_sets[final.change_set_id] : undefined;
    items.push({
      ...pendingAssistant(`h${String(final.id)}`),
      speaker: final.agent_id,
      text: final.content,
      streaming: false,
      steps: group.slice(0, -1).map((m) => ({
        agentId: m.agent_id ?? "",
        name: names[m.agent_id ?? ""] ?? m.agent_id ?? "",
        tools: [],
        reply: m.content,
      })),
      changeSetId: final.change_set_id,
      changes: set?.changes ?? [],
      undone: set?.undone ?? false,
    });
    group = [];
  };

  for (const message of history.messages) {
    if (message.kind) {
      // briefing / check-in / follow-up: its own item, never a step of an answer
      flush();
      items.push({
        ...pendingAssistant(`h${String(message.id)}`),
        speaker: message.agent_id,
        text: message.content,
        streaming: false,
        origin: message.kind,
      });
    } else if (message.role === "user") {
      flush();
      items.push({
        kind: "user",
        id: `h${String(message.id)}`,
        text: message.content,
        images: (message.attachments ?? []).map((a) => ({
          url: a.url,
          name: a.filename ?? `#${String(a.id)}`,
          mime: a.mime,
        })),
      });
    } else {
      group.push(message);
    }
  }
  flush();
  return items;
}
