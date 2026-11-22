import { useState } from "react";

import { apiPost } from "../api/client";
import { tr } from "../i18n/tr";
import type { AssistantItem } from "./model";

type State = { step: "idle" | "open" | "sending" } | { step: "sent"; id: number } | { step: "failed" };

/** 👎 "Hatalı" under an answer: a short note, then the server keeps the message, the answer,
 *  who answered, the tools and the log lines (app/api/bugs.py). The one write the UI does
 *  besides "Geri al" (it is about the app, not the user's data). */
export function ReportBug({ item, userText }: { item: AssistantItem; userText: string }) {
  const [state, setState] = useState<State>({ step: "idle" });
  const [note, setNote] = useState("");
  if (item.streaming) return null;

  async function send() {
    setState({ step: "sending" });
    try {
      const report = await apiPost<{ id: number }>("/bug-reports", {
        message_id: item.messageId,
        note: note.trim(),
        source: "web",
        // a failed answer was never stored: send what is on the screen
        ...(item.messageId === null ? { user_text: userText, reply_text: item.text, error: item.error } : {}),
      });
      setState({ step: "sent", id: report.id });
    } catch {
      setState({ step: "failed" });
    }
  }

  if (state.step === "sent") {
    return (
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400" role="status">
        {tr.bugs.sent(state.id)}
      </p>
    );
  }
  if (state.step === "idle") {
    return (
      <button
        type="button"
        onClick={() => {
          setState({ step: "open" });
        }}
        title={tr.bugs.buttonHint}
        className="mt-1 inline-flex min-h-7 items-center gap-1 rounded-full px-2 text-xs text-slate-400 hover:bg-slate-900/5 hover:text-rose-600 dark:hover:bg-white/10 dark:hover:text-rose-300"
      >
        <span aria-hidden>👎</span> {tr.bugs.button}
      </button>
    );
  }
  return (
    <form
      className="mt-2 flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        void send();
      }}
    >
      <textarea
        value={note}
        onChange={(event) => {
          setNote(event.target.value);
        }}
        maxLength={2000}
        rows={2}
        autoFocus
        placeholder={tr.bugs.placeholder}
        aria-label={tr.bugs.placeholder}
        className="yv-glass w-full resize-none rounded-2xl px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-500/40"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          disabled={state.step === "sending"}
          className="min-h-8 rounded-full bg-rose-600 px-3 text-xs font-medium text-white hover:brightness-110 disabled:opacity-60"
        >
          {state.step === "sending" ? tr.bugs.sending : tr.bugs.send}
        </button>
        <button
          type="button"
          onClick={() => {
            setState({ step: "idle" });
          }}
          className="min-h-8 rounded-full px-3 text-xs text-slate-500 hover:bg-slate-900/5 dark:hover:bg-white/10"
        >
          {tr.bugs.cancel}
        </button>
        {state.step === "failed" && (
          <span className="text-xs text-rose-600 dark:text-rose-400" role="alert">
            {tr.bugs.failed}
          </span>
        )}
      </div>
    </form>
  );
}
