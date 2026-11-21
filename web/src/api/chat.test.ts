import { afterEach, describe, expect, it, vi } from "vitest";

import { runStream } from "./chat";
import type { ChatEvent } from "./types";

function sseBody(chunks: string[], hang = false): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      if (!hang) controller.close();
    },
  });
}

function serve(body: ReadableStream<Uint8Array>, status = 200): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(body, { status }))),
  );
}

async function run(idleMs = 1_000, signal?: AbortSignal): Promise<ChatEvent[]> {
  const events: ChatEvent[] = [];
  await runStream("/api/chat/stream", {}, (e) => events.push(e), signal, idleMs);
  return events;
}

const data = (event: object): string => `data: ${JSON.stringify(event)}\n\n`;

describe("chat stream (Y3)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("drops pings and passes done through", async () => {
    serve(sseBody([data({ type: "turn", agent_id: "yaver" }), data({ type: "ping" }), data({ type: "done", reply: "ok" })]));
    expect((await run()).map((e) => e.type)).toEqual(["turn", "done"]);
  });

  it("a stream closing without done/error ends with interrupted", async () => {
    serve(sseBody([data({ type: "turn", agent_id: "yaver" })]));
    expect((await run()).at(-1)).toEqual({ type: "error", code: "interrupted" });
  });

  it("silence longer than the idle timeout ends with timeout", async () => {
    serve(sseBody([data({ type: "turn", agent_id: "yaver" })], true));
    expect((await run(50)).at(-1)).toEqual({ type: "error", code: "timeout" });
  });

  it("an HTTP error ends with network", async () => {
    serve(sseBody([]), 502);
    expect(await run()).toEqual([{ type: "error", code: "network" }]);
  });

  it("the user aborting (new chat) ends silently", async () => {
    serve(sseBody([data({ type: "turn", agent_id: "yaver" })], true));
    const controller = new AbortController();
    setTimeout(() => {
      controller.abort();
    }, 20);
    expect(await run(1_000, controller.signal)).toEqual([{ type: "turn", agent_id: "yaver" }]);
  });
});
