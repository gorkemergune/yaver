/**
 * Minimal server-sent-events parser for a fetch() body (EventSource can't POST).
 * Yields the JSON payload of every `data:` event.
 */
export async function* readEvents<T>(body: ReadableStream<Uint8Array>, signal?: AbortSignal): AsyncGenerator<T> {
  const reader = body.getReader();
  // aborting ends a pending read (not every body errors on abort by itself)
  const cancel = (): void => {
    void reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener("abort", cancel, { once: true });
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      yield* drain<T>(buffer, (rest) => (buffer = rest));
    }
    buffer += decoder.decode();
    yield* drain<T>(`${buffer}\n\n`, () => undefined);
  } finally {
    signal?.removeEventListener("abort", cancel);
    reader.releaseLock();
  }
}

function* drain<T>(buffer: string, keep: (rest: string) => void): Generator<T> {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const blocks = normalized.split("\n\n");
  keep(blocks.pop() ?? "");
  for (const block of blocks) {
    const data = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (data) yield JSON.parse(data) as T;
  }
}
