import { useEffect, useMemo, useRef, useState } from "react";

import { useOnboardingStatus } from "../api/queries";
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
    const all = [chat.team.coordinator, ...chat.team.agents];
    if (chat.team.onboarding) all.push(chat.team.onboarding);
    return Object.fromEntries(all.map((m) => [m.id, m]));
  }, [chat.team]);
  const onboarding = useOnboardingStatus();
  const [skipped, setSkipped] = useState(onboardingSkipped);

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
        {chat.items.length === 0 && onboarding.data?.needed && !skipped ? (
          <OnboardingCard
            busy={chat.busy}
            onStart={() => void chat.send(tr.onboarding.startMessage, "onboarding")}
            onSkip={() => {
              rememberSkip();
              setSkipped(true);
            }}
          />
        ) : chat.items.length === 0 ? (
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
        {item.status && item.streaming && (
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-400" role="status">
            {tr.chat.waiting(item.status.provider)}
          </p>
        )}
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

const SKIP_KEY = "yaver.onboarding.skipped";

function onboardingSkipped(): boolean {
  try {
    return localStorage.getItem(SKIP_KEY) === "1";
  } catch {
    return false;
  }
}

function rememberSkip(): void {
  try {
    localStorage.setItem(SKIP_KEY, "1");
  } catch {
    // shown again next time; harmless
  }
}

/** First run: nothing set up yet. Starts the setup conversation with the assistant. */
function OnboardingCard({ busy, onStart, onSkip }: { busy: boolean; onStart: () => void; onSkip: () => void }) {
  return (
    <div className="mx-auto flex h-full max-w-md flex-col justify-center gap-4">
      <img src="/favicon.svg" alt="" className="h-12 w-12 self-center" />
      <h2 className="text-center text-2xl font-semibold">{tr.onboarding.title}</h2>
      <p className="text-center text-sm text-slate-500 dark:text-slate-400">{tr.onboarding.intro}</p>
      <ul className="space-y-1.5 rounded-2xl bg-white p-4 text-sm shadow-sm ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-800">
        {tr.onboarding.steps.map((step) => (
          <li key={step} className="flex gap-2">
            <span className="text-indigo-500" aria-hidden>
              •
            </span>
            {step}
          </li>
        ))}
      </ul>
      <p className="text-center text-xs text-slate-500 dark:text-slate-400">{tr.onboarding.pasteHint}</p>
      <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
        <button
          type="button"
          onClick={onStart}
          disabled={busy}
          className="min-h-11 rounded-xl bg-indigo-600 px-5 font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {tr.onboarding.start}
        </button>
        <button
          type="button"
          onClick={onSkip}
          className="min-h-11 rounded-xl px-5 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          {tr.onboarding.skip}
        </button>
      </div>
    </div>
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
