import { readEvents } from "../lib/sse";
import type { ChatEvent, ChatMode } from "./types";

/** POST /api/chat/stream; calls onEvent for every server-sent event. */
export async function streamChat(
  message: string,
  conversationId: number | null,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
  mode: ChatMode = "chat",
  attachmentIds: number[] = [],
): Promise<void> {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ message, conversation_id: conversationId, mode, attachment_ids: attachmentIds }),
    signal,
  });
  if (!response.ok || !response.body) {
    onEvent({ type: "error", code: "network" });
    return;
  }
  for await (const event of readEvents<ChatEvent>(response.body)) onEvent(event);
}
