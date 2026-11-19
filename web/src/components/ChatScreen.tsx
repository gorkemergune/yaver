import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { tr } from "../i18n/tr";
import { ConnectionStatus } from "./ConnectionStatus";

interface LocalMessage {
  id: number;
  text: string;
}

/**
 * Empty chat shell (TASKS 0.1). Messages stay local until the agent loop lands in 0.5;
 * the screen is wired for streaming replies, change cards and undo later.
 */
export function ChatScreen() {
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [draft, setDraft] = useState("");
  const nextId = useRef(1);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    setMessages((prev) => [...prev, { id: nextId.current++, text: trimmed }]);
    setDraft("");
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    send(draft);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send(draft);
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <h1 className="text-lg font-semibold">{tr.appName}</h1>
        </div>
        <ConnectionStatus />
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <h2 className="text-2xl font-semibold">{tr.chat.emptyTitle}</h2>
            <p className="max-w-md text-sm text-slate-500 dark:text-slate-400">{tr.chat.emptyHint}</p>
            <div className="flex flex-wrap justify-center gap-2">
              {tr.chat.examples.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setDraft(example)}
                  className="rounded-full border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ul className="flex flex-col gap-3">
            {messages.map((message) => (
              <li key={message.id} className="flex justify-end">
                <p className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-indigo-600 px-4 py-2 text-white">
                  {message.text}
                </p>
              </li>
            ))}
            <li className="text-center text-xs text-slate-400">{tr.chat.agentNotConnected}</li>
          </ul>
        )}
        <div ref={bottomRef} />
      </main>

      <form
        onSubmit={onSubmit}
        className="flex items-end gap-2 border-t border-slate-200 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] dark:border-slate-800"
      >
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={tr.chat.inputPlaceholder}
          rows={1}
          className="max-h-40 flex-1 resize-none rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-base outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 dark:border-slate-700 dark:bg-slate-900"
        />
        <button
          type="submit"
          disabled={!draft.trim()}
          className="rounded-xl bg-indigo-600 px-4 py-2.5 font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {tr.chat.send}
        </button>
      </form>
    </div>
  );
}
