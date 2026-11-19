import { describe, expect, it } from "vitest";

import { readEvents } from "./sse";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>): Promise<unknown[]> {
  const events: unknown[] = [];
  for await (const event of readEvents(stream)) events.push(event);
  return events;
}

describe("readEvents", () => {
  it("parses events split across chunks", async () => {
    const events = await collect(
      streamOf('data: {"type":"text","del', 'ta":"Mer"}\n\ndata: {"type":"te', 'xt","delta":"haba"}\n\n'),
    );
    expect(events).toEqual([
      { type: "text", delta: "Mer" },
      { type: "text", delta: "haba" },
    ]);
  });

  it("handles CRLF, multi-byte characters and a missing final blank line", async () => {
    const bytes = new TextEncoder().encode('data: {"t":"çğüş"}\r\n\r\ndata: {"t":"ı"}');
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, 13)); // cuts inside "ç"
        controller.enqueue(bytes.slice(13));
        controller.close();
      },
    });
    expect(await collect(stream)).toEqual([{ t: "çğüş" }, { t: "ı" }]);
  });

  it("ignores comments and empty blocks", async () => {
    expect(await collect(streamOf(": ping\n\n\n\ndata: 1\n\n"))).toEqual([1]);
  });
});
