import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { streamEmployeeChat } from "../api/chat";
import { apiGet, apiPost } from "../api/client";
import { MUTABLE_KEYS } from "../api/queries";
import type { HistoryResponse } from "../api/types";
import type { UndoState } from "../chat/useChat";
import { applyEvent, historyToItems, pendingAssistant, type AssistantItem, type ChatItem } from "../chat/model";
import { officeKeys } from "./useOffice";

/** The office panel's direct chat with one employee (its latest direct conversation). */
export function useEmployeeChat(employeeId: string, names: Record<string, string>) {
  const queryClient = useQueryClient();
  const [items, setItems] = useState<ChatItem[]>([]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [undo, setUndo] = useState<UndoState>({ pending: new Set(), failed: new Set() });
  const counter = useRef(0);
  const asked = useRef(new Map<string, string>()); // answer id -> question, for "Tekrar dene"
  const namesRef = useRef(names);
  useEffect(() => {
    namesRef.current = names;
  }, [names]);

  // the panel is keyed by employee: a new employee is a fresh hook
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const found = await apiGet<{ conversation_id: number | null }>(
          `/employees/${encodeURIComponent(employeeId)}/chat`,
          { signal: controller.signal },
        );
        if (found.conversation_id === null) return;
        const history = await apiGet<HistoryResponse>(`/conversations/${String(found.conversation_id)}/messages?limit=20`, {
          signal: controller.signal,
        });
        setItems(historyToItems(history, namesRef.current));
        setConversationId(found.conversation_id);
      } catch {
        // no history: the panel starts empty
      }
    })();
    return () => {
      controller.abort();
    };
  }, [employeeId]);

  const refresh = useCallback(() => {
    for (const key of MUTABLE_KEYS) void queryClient.invalidateQueries({ queryKey: key });
    void queryClient.invalidateQueries({ queryKey: officeKeys.notes(employeeId) });
    void queryClient.invalidateQueries({ queryKey: officeKeys.tasks(employeeId) });
  }, [queryClient, employeeId]);

  const send = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      counter.current += 1;
      const answerId = `e${String(counter.current)}`;
      asked.current.set(answerId, message);
      setItems((prev) => [...prev, { kind: "user", id: `q${String(counter.current)}`, text: message, images: [] }, pendingAssistant(answerId)]);
      setBusy(true);
      const update = (fn: (item: AssistantItem) => AssistantItem): void => {
        setItems((prev) => prev.map((item) => (item.id === answerId && item.kind === "assistant" ? fn(item) : item)));
      };
      try {
        await streamEmployeeChat(employeeId, message, conversationId, (event) => {
          update((item) => applyEvent(item, event, namesRef.current));
          if (event.type === "done") setConversationId(event.conversation_id);
        });
      } catch {
        update((item) => ({ ...item, streaming: false, error: "network" }));
      } finally {
        update((item) => (item.streaming ? { ...item, streaming: false } : item));
        setBusy(false);
        refresh();
      }
    },
    [busy, conversationId, employeeId, refresh],
  );

  const retry = useCallback(
    (answerId: string) => {
      const question = asked.current.get(answerId);
      if (question === undefined || busy) return;
      setItems((prev) => {
        const at = prev.findIndex((item) => item.id === answerId);
        if (at < 0) return prev;
        const from = at > 0 && prev[at - 1]?.kind === "user" ? at - 1 : at;
        return [...prev.slice(0, from), ...prev.slice(at + 1)];
      });
      void send(question);
    },
    [busy, send],
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
        refresh();
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
    [refresh],
  );

  return { items, busy, undo, send, retry, undoChange };
}
