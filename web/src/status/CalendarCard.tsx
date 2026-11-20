import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiGet, apiPost } from "../api/client";
import { tr } from "../i18n/tr";
import { subscriptionUrls } from "../lib/calendar";
import { Card } from "./Card";

export function CalendarCard() {
  const client = useQueryClient();
  const sub = useQuery({
    queryKey: ["calendar-subscription"],
    queryFn: ({ signal }) => apiGet<{ path: string }>("/calendar/subscription", { signal }),
    staleTime: Infinity,
  });
  const [note, setNote] = useState<string | null>(null);
  if (!sub.data) return null;
  const urls = subscriptionUrls(window.location.origin, sub.data.path);
  const button = "rounded-full px-4 py-2 text-sm font-semibold transition-colors";
  return (
    <Card title={tr.calendar.title}>
      <p className="text-sm text-slate-600 dark:text-slate-300">{tr.calendar.what}</p>
      <code className="yv-inset mt-3 block break-all rounded-xl px-3 py-2 text-xs">{urls.webcal}</code>
      <div className="mt-3 flex flex-wrap gap-2">
        <a
          href={urls.webcal}
          className={`${button} bg-gradient-to-r from-indigo-500 to-fuchsia-500 text-white`}
        >
          {tr.calendar.open}
        </a>
        <button
          type="button"
          onClick={() => {
            navigator.clipboard.writeText(urls.webcal).then(
              () => {
                setNote(tr.calendar.copied);
              },
              () => {
                setNote(tr.calendar.copyFailed);
              },
            );
          }}
          className={`${button} bg-indigo-500/10 text-indigo-700 hover:bg-indigo-500/20 dark:text-indigo-300`}
        >
          {tr.calendar.copy}
        </button>
        <button
          type="button"
          onClick={() => {
            if (!window.confirm(tr.calendar.rotateConfirm)) return;
            apiPost<{ path: string }>("/calendar/subscription/rotate").then(
              (fresh) => {
                client.setQueryData(["calendar-subscription"], fresh);
                setNote(tr.calendar.rotated);
              },
              () => {
                setNote(tr.calendar.copyFailed);
              },
            );
          }}
          className={`${button} text-slate-600 hover:bg-white/60 dark:text-slate-300 dark:hover:bg-white/10`}
        >
          {tr.calendar.rotate}
        </button>
      </div>
      {note && (
        <p role="status" className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          {note}
        </p>
      )}
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">{tr.calendar.howto}</p>
    </Card>
  );
}
