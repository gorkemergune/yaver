import { describe, expect, it } from "vitest";

import type { ChatEvent, HistoryResponse } from "../api/types";
import { applyEvent, historyToItems, pendingAssistant, stepSummary } from "./model";

const names = { yaver: "Yaver", academic: "Friday", discipline: "Karen" };

function run(events: ChatEvent[]) {
  return events.reduce((item, event) => applyEvent(item, event, names), pendingAssistant("a1"));
}

describe("applyEvent", () => {
  it("collects yaver steps and streams the speaker's text", () => {
    const item = run([
      { type: "turn", agent_id: "yaver" },
      { type: "delegate", agent_id: "academic", name: "Friday", instruction: "Bugün linear iptal" },
      { type: "turn", agent_id: "academic" },
      { type: "tool", agent_id: "academic", tool: "cancel_block_on", arguments: {}, error: null, mutates: true },
      { type: "agent_reply", agent_id: "academic", name: "Friday", reply: "İptal edildi." },
      { type: "turn", agent_id: "yaver" },
      { type: "text", agent_id: "yaver", delta: "Friday: " },
      { type: "text", agent_id: "yaver", delta: "linear iptal." },
    ]);

    expect(item.text).toBe("Friday: linear iptal.");
    expect(item.speaker).toBe("yaver");
    expect(item.steps).toEqual([
      {
        agentId: "academic",
        name: "Friday",
        instruction: "Bugün linear iptal",
        tools: [{ tool: "cancel_block_on", error: null, mutates: true }],
        reply: "İptal edildi.",
      },
    ]);
    expect(item.streaming).toBe(true);
  });

  it("a new turn or a retry of the speaker drops the draft", () => {
    const afterTurn = run([
      { type: "text", agent_id: "yaver", delta: "Bakıyorum…" },
      { type: "turn", agent_id: "yaver" },
    ]);
    const afterReset = run([
      { type: "text", agent_id: "yaver", delta: "Yarım" },
      { type: "reset", agent_id: "yaver" },
      { type: "text", agent_id: "yaver", delta: "Tam cevap" },
    ]);

    expect(afterTurn.text).toBe("");
    expect(afterReset.text).toBe("Tam cevap");
  });

  it("done carries the final answer and the change set", () => {
    const item = run([
      { type: "text", agent_id: "yaver", delta: "taslak" },
      {
        type: "done",
        conversation_id: 1,
        reply: "Tamamlandı.",
        speaker: "yaver",
        change_set_id: "cs-1",
        agents: [],
        changes: [{ entity: "events", op: "create", agent_id: "agenda", data: {}, undone: false }],
        cost_usd: "0.001",
      },
    ]);

    expect(item).toMatchObject({ text: "Tamamlandı.", streaming: false, changeSetId: "cs-1" });
    expect(item.changes).toHaveLength(1);
  });

  it("errors stop streaming", () => {
    expect(run([{ type: "error", code: "llm_unavailable" }])).toMatchObject({
      streaming: false,
      error: "llm_unavailable",
    });
  });

  it("tool calls of the coordinator itself (fast path) become its own step", () => {
    const item = run([
      { type: "tool", agent_id: "yaver", tool: "cancel_block_on", arguments: {}, error: null, mutates: true },
    ]);
    expect(item.steps[0]?.name).toBe("Yaver");
  });
});

describe("stepSummary", () => {
  it("counts successful changes, else question or look", () => {
    const base = { agentId: "x", name: "X" };
    expect(
      stepSummary({ ...base, tools: [{ tool: "add_event", error: null, mutates: true }, { tool: "add_event", error: "x", mutates: true }] }),
    ).toEqual({ kind: "changed", count: 1 });
    expect(stepSummary({ ...base, tools: [], reply: "Hangi gün?" })).toEqual({ kind: "asked", count: 0 });
    expect(stepSummary({ ...base, tools: [{ tool: "get_day_plan", error: null, mutates: false }] })).toEqual({
      kind: "looked",
      count: 0,
    });
  });
});

describe("historyToItems", () => {
  it("groups yaver replies under the final answer", () => {
    const history: HistoryResponse = {
      conversation_id: 1,
      messages: [
        { id: 1, role: "user", agent_id: null, content: "kurulum", created_at: "", change_set_id: null },
        { id: 2, role: "assistant", agent_id: "academic", content: "Dersler eklendi", created_at: "", change_set_id: "cs" },
        { id: 3, role: "assistant", agent_id: "yaver", content: "Tamam", created_at: "", change_set_id: "cs" },
        { id: 4, role: "user", agent_id: null, content: "teşekkürler", created_at: "", change_set_id: null },
        { id: 5, role: "assistant", agent_id: "yaver", content: "Rica ederim", created_at: "", change_set_id: null },
      ],
      change_sets: { cs: { changes: [], undone: true } },
    };

    const items = historyToItems(history, names);

    expect(items.map((i) => i.kind)).toEqual(["user", "assistant", "user", "assistant"]);
    const first = items[1];
    expect(first?.kind === "assistant" && first.steps.map((s) => s.name)).toEqual(["Friday"]);
    expect(first?.kind === "assistant" && first.undone).toBe(true);
  });
});
