import { useEffect, useMemo, useRef, useState } from "react";

import type { Member } from "../api/types";
import { AgentTag } from "../components/AgentTag";
import { PlusIcon } from "../components/icons";
import { Markdown } from "../components/Markdown";
import { tr } from "../i18n/tr";
import { ChangeCard } from "./ChangeCard";
import { Composer } from "./Composer";
import type { AssistantItem } from "./model";
import { Steps } from "./Steps";
import { useChat, type UndoState } from "./useChat";

export function ChatView() {
  const chat = useChat();
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  const members = useMemo<Record<string, Member>>(() => {
    if (!chat.team) return {};
    return Object.fromEntries([chat.team.coordinator, ...chat.team.agents].map((m) => [m.id, m]));
  }, [chat.team]);

  const last = chat.items[chat.items.length - 1];
  const lastText = last?.kind === "assistant" ? last.text : "";
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [chat.items.length, lastText]);

  function send() {
    const text = draft;
    setDraft("");
    void chat.send(text);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto px-3 py-4">
        {chat.items.length === 0 ? (
          <Empty onPick={setDraft} />
        ) : (
          <ul className="mx-auto flex max-w-2xl flex-col gap-4">
            {chat.items.map((item) =>
              item.kind === "user" ? (
                <li key={item.id} className="flex justify-end">
                  <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2 text-white">
                    {item.text}
                  </p>
                </li>
              ) : (
                <Answer
                  key={item.id}
                  item={item}
                  members={members}
                  undo={chat.undo}
                  onUndo={(changeSetId) => void chat.undoChange(item.id, changeSetId)}
                />
              ),
            )}
          </ul>
        )}
        <div ref={bottom} />
      </div>
      {chat.items.length > 0 && (
        <div className="flex justify-center pb-1">
          <button
            type="button"
            onClick={chat.newChat}
            disabled={chat.busy}
            className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs text-slate-500 hover:bg-slate-200/60 disabled:opacity-40 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            <PlusIcon width={14} height={14} />
            {tr.chat.newChat}
          </button>
        </div>
      )}
      <Composer value={draft} onChange={setDraft} onSend={send} busy={chat.busy} />
    </div>
  );
}

function Answer({
  item,
  members,
  undo,
  onUndo,
}: {
  item: AssistantItem;
  members: Record<string, Member>;
  undo: UndoState;
  onUndo: (changeSetId: string) => void;
}) {
  const speaker = item.speaker ? members[item.speaker] : undefined;
  return (
    <li className="flex flex-col items-start">
      <div className="w-full max-w-[92%] rounded-2xl rounded-bl-md bg-white px-4 py-3 shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
        <div className="mb-1.5">
          <AgentTag member={speaker} fallback={tr.appName} />
        </div>
        {item.text ? (
          <Markdown text={item.text} />
        ) : item.streaming ? (
          <Typing />
        ) : null}
        {item.error && (
          <p className="text-sm text-rose-600 dark:text-rose-400">
            {tr.chat.errors[item.error] ?? tr.chat.errors.internal}
          </p>
        )}
        <Steps steps={item.steps} members={members} />
        {item.changeSetId && (
          <ChangeCard
            changes={item.changes}
            undone={item.undone}
            pending={undo.pending.has(item.id)}
            failed={undo.failed.has(item.id)}
            onUndo={() => {
              if (item.changeSetId) onUndo(item.changeSetId);
            }}
          />
        )}
      </div>
    </li>
  );
}

function Typing() {
  return (
    <span className="inline-flex items-center gap-1 py-1 text-slate-400" aria-label={tr.chat.thinking}>
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="h-1.5 w-1.5 animate-bounce rounded-full bg-current"
          style={{ animationDelay: `${String(delay)}ms` }}
        />
      ))}
    </span>
  );
}

function Empty({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center gap-4 text-center">
      <img src="/favicon.svg" alt="" className="h-12 w-12" />
      <h2 className="text-2xl font-semibold">{tr.chat.emptyTitle}</h2>
      <p className="text-sm text-slate-500 dark:text-slate-400">{tr.chat.emptyHint}</p>
      <div className="flex flex-wrap justify-center gap-2">
        {tr.chat.examples.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => {
              onPick(example);
            }}
            className="rounded-full border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}
