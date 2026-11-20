import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { apiGet } from "../api/client";
import type { OfficeEvent, OfficeSnapshot } from "../api/types";
import { tr } from "../i18n/tr";
import { applyOfficeEvent, feedLine, type Staff } from "./model";

export type Link = "connecting" | "live" | "reconnecting";

export interface FeedItem {
  id: string;
  employeeId: string;
  text: string;
  at: string; // ISO time
}

const FEED_SIZE = 8;
const MAX_RETRY_MS = 15_000;
// The server sends a ping every 15 s: this long without any event = a dead stream (a proxy
// can keep it open after the API went away, a laptop can wake up on a stale one).
export const SILENCE_MS = 40_000;

export const officeKeys = {
  notes: (id: string) => ["office", "notes", id] as const,
  tasks: (id: string) => ["office", "tasks", id] as const,
};

/**
 * The live office: /api/office/snapshot for the first paint, then /api/office/stream
 * (SSE). Every (re)connect starts with a snapshot, so a dropped connection loses nothing;
 * if the browser gives up (server down, 401), we reconnect with a growing delay.
 */
export function useOffice() {
  const queryClient = useQueryClient();
  const [staff, setStaff] = useState<Staff>({});
  const [ready, setReady] = useState<boolean | null>(null); // null: not known yet
  const [link, setLink] = useState<Link>("connecting");
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const current = useRef<Staff>({});

  useEffect(() => {
    let source: EventSource | null = null;
    let timer: number | undefined;
    let attempt = 0;
    let stopped = false;
    let counter = 0;
    let lastSeen = Date.now();

    const push = (employeeId: string, text: string, at: string): void => {
      counter += 1;
      const item = { id: `f${String(counter)}`, employeeId, text, at };
      setFeed((prev) => [item, ...prev].slice(0, FEED_SIZE));
    };

    const handle = (event: OfficeEvent): void => {
      const before = current.current;
      if (event.type === "state") {
        const line = feedLine(before[event.employee_id], event, before);
        if (line) push(event.employee_id, line, event.ts);
        if (event.activity === "break") void queryClient.invalidateQueries({ queryKey: officeKeys.tasks(event.employee_id) });
      } else if (event.type === "note") {
        push(event.employee_id, tr.office.feed.noted(event.note.content), event.ts);
        void queryClient.invalidateQueries({ queryKey: officeKeys.notes(event.employee_id) });
      } else if (event.type === "snapshot") {
        setReady(event.ready);
      } else {
        return; // ping: only keeps the watchdog quiet
      }
      const next = applyOfficeEvent(before, event);
      current.current = next;
      setStaff(next);
    };

    void apiGet<OfficeSnapshot>("/office/snapshot")
      .then((snapshot) => {
        if (!stopped && Object.keys(current.current).length === 0) handle({ type: "snapshot", ...snapshot });
      })
      .catch(() => undefined); // the stream brings it too

    const connect = (): void => {
      lastSeen = Date.now();
      source = new EventSource("/api/office/stream");
      source.onopen = () => {
        attempt = 0;
        lastSeen = Date.now();
        setLink("live");
      };
      source.onmessage = (message: MessageEvent<string>) => {
        lastSeen = Date.now();
        setLink("live");
        try {
          handle(JSON.parse(message.data) as OfficeEvent);
        } catch {
          // a broken event: the next snapshot puts things right
        }
      };
      source.onerror = () => {
        setLink("reconnecting");
        if (source?.readyState === EventSource.CLOSED) {
          source.close();
          const delay = Math.min(MAX_RETRY_MS, 1000 * 2 ** attempt);
          attempt += 1;
          timer = window.setTimeout(connect, delay);
        } // otherwise the browser retries by itself (retry: 3000)
      };
    };
    connect();
    const watchdog = window.setInterval(() => {
      if (stopped || !source || Date.now() - lastSeen < SILENCE_MS) return;
      source.close(); // silent for too long: start over (the server sends a snapshot first)
      setLink("reconnecting");
      window.clearTimeout(timer);
      connect();
    }, 5_000);
    return () => {
      stopped = true;
      source?.close();
      window.clearTimeout(timer);
      window.clearInterval(watchdog);
    };
  }, [queryClient]);

  return { staff, ready, link, feed };
}
