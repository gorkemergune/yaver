import { readEvents } from "../lib/sse";
import type { ChatEvent, ChatMode } from "./types";

/**
 * The server sends a `ping` every 15 s while an answer is slow (app/api/chat.py), so this
 * much silence means the stream is dead: hung request, a proxy buffering it, a lost network.
 */
export const IDLE_TIMEOUT_MS = 45_000;

/**
 * POSTs to a chat stream and calls onEvent for every event, except `ping`. Always ends with
 * exactly one terminal event (`done` or `error`): `network` when the request fails, `timeout`
 * after IDLE_TIMEOUT_MS without a byte, `interrupted` when the stream closes without one.
 * Aborting `signal` (the user started a new chat) ends silently.
 */
export async function runStream(
  url: string,
  body: unknown,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
  idleMs: number = IDLE_TIMEOUT_MS,
): Promise<void> {
  const controller = new AbortController();
  const stop = (): void => {
    controller.abort();
  };
  signal?.addEventListener("abort", stop, { once: true });
  const state = { idle: false }; // set by the timer (an object: TS can't see closure writes)
  let timer: ReturnType<typeof setTimeout> | undefined;
  const arm = (): void => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.idle = true;
      controller.abort();
    }, idleMs);
  };
  let ended = false;
  const end = (event: ChatEvent): void => {
    if (ended || signal?.aborted) return;
    ended = true;
    onEvent(event);
  };
  arm();
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok || !response.body) {
      end({ type: "error", code: "network" });
      return;
    }
    for await (const event of readEvents<ChatEvent>(response.body, controller.signal)) {
      arm();
      if (event.type === "ping") continue;
      if (event.type === "done" || event.type === "error") end(event);
      else onEvent(event);
    }
    if (controller.signal.aborted) throw new Error("aborted");
    end({ type: "error", code: "interrupted" });
  } catch {
    end({ type: "error", code: state.idle ? "timeout" : "network" });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", stop);
  }
}

/** POST /api/chat/stream. */
export function streamChat(
  message: string,
  conversationId: number | null,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
  mode: ChatMode = "chat",
  attachmentIds: number[] = [],
): Promise<void> {
  return runStream(
    "/api/chat/stream",
    { message, conversation_id: conversationId, mode, attachment_ids: attachmentIds },
    onEvent,
    signal,
  );
}

/** POST /api/employees/{id}/chat/stream: a direct chat with one employee (same events). */
export function streamEmployeeChat(
  employeeId: string,
  message: string,
  conversationId: number | null,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return runStream(
    `/api/employees/${encodeURIComponent(employeeId)}/chat/stream`,
    { message, conversation_id: conversationId },
    onEvent,
    signal,
  );
}
