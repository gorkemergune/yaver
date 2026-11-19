import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { streamChat } from "../api/chat";
import { apiGet, apiPost } from "../api/client";
import { MUTABLE_KEYS, useTeam } from "../api/queries";
import type { HistoryResponse } from "../api/types";
import { applyEvent, historyToItems, pendingAssistant, type AssistantItem, type ChatItem } from "./model";

const KEY = "yaver.conversation";

function storedConversation(): number | null {
  try {
    const value = Number(localStorage.getItem(KEY));
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

function storeConversation(id: number | null): void {
  try {
    if (id === null) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, String(id));
  } catch {
    // not remembered across reloads; the chat still works
  }
}

export interface UndoState {
  pending: Set<string>;
  failed: Set<string>;
}

export function useChat() {
  const queryClient = useQueryClient();
  const team = useTeam();
  const names = useMemo<Record<string, string>>(() => {
    if (!team.data) return {};
    const members = [team.data.coordinator, ...team.data.agents];
    return Object.fromEntries(members.map((m) => [m.id, m.name]));
  }, [team.data]);

  const [items, setItems] = useState<ChatItem[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(storedConversation);
  const [busy, setBusy] = useState(false);
  const [undo, setUndo] = useState<UndoState>({ pending: new Set(), failed: new Set() });
  const [loaded, setLoaded] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const counter = useRef(0);

  const refreshData = useCallback(() => {
    for (const key of MUTABLE_KEYS) void queryClient.invalidateQueries({ queryKey: key });
  }, [queryClient]);

  // Restore the last conversation once the team names are known.
  useEffect(() => {
    if (loaded || !team.data) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const id =
          storedConversation() ??
          (await apiGet<{ conversation_id: number | null }>("/conversations/latest", {
            signal: controller.signal,
          })).conversation_id;
        if (id !== null) {
          const history = await apiGet<HistoryResponse>(`/conversations/${String(id)}/messages`, {
            signal: controller.signal,
          });
          setItems(historyToItems(history, names));
          setConversationId(id);
          storeConversation(id);
        }
      } catch {
        storeConversation(null); // stale id (e.g. database reset): start fresh
      } finally {
        if (!controller.signal.aborted) setLoaded(true);
      }
    })();
    return () => {
      controller.abort();
    };
  }, [loaded, team.data, names]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      counter.current += 1;
      const userId = `u${String(counter.current)}`;
      const answerId = `a${String(counter.current)}`;
      setItems((prev) => [...prev, { kind: "user", id: userId, text: message }, pendingAssistant(answerId)]);
      setBusy(true);
      const controller = new AbortController();
      abort.current = controller;

      const update = (fn: (item: AssistantItem) => AssistantItem): void => {
        setItems((prev) => prev.map((item) => (item.id === answerId && item.kind === "assistant" ? fn(item) : item)));
      };

      try {
        await streamChat(
          message,
          conversationId,
          (event) => {
            update((item) => applyEvent(item, event, names));
            if (event.type === "done") {
              setConversationId(event.conversation_id);
              storeConversation(event.conversation_id);
            }
          },
          controller.signal,
        );
      } catch {
        if (!controller.signal.aborted) update((item) => ({ ...item, streaming: false, error: "network" }));
      } finally {
        update((item) => (item.streaming ? { ...item, streaming: false } : item));
        setBusy(false);
        abort.current = null;
        refreshData();
      }
    },
    [busy, conversationId, names, refreshData],
  );

  const undoChange = useCallback(
    async (itemId: string, changeSetId: string) => {
      setUndo((s) => ({ pending: new Set(s.pending).add(itemId), failed: s.failed }));
      let ok = false;
      try {
        await apiPost(`/changes/${changeSetId}/undo`);
        ok = true;
      } catch {
        ok = false;
      }
      if (ok) {
        setItems((prev) => prev.map((item) => (item.id === itemId && item.kind === "assistant" ? { ...item, undone: true } : item)));
        refreshData();
      }
      setUndo((s) => {
        const pending = new Set(s.pending);
        pending.delete(itemId);
        const failed = new Set(s.failed);
        if (ok) failed.delete(itemId);
        else failed.add(itemId);
        return { pending, failed };
      });
    },
    [refreshData],
  );

  const newChat = useCallback(() => {
    abort.current?.abort();
    setItems([]);
    setConversationId(null);
    storeConversation(null);
  }, []);

  return { items, busy, send, undoChange, undo, newChat, team: team.data, names };
}
