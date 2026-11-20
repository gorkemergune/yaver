import { useEffect, useMemo, useRef, useState } from "react";

import { useOnboardingStatus } from "../api/queries";
import type { Member, Team } from "../api/types";
import { YaverAvatar } from "../components/Yaver";
import { PlusIcon } from "../components/icons";
import { Markdown } from "../components/Markdown";
import { tr } from "../i18n/tr";
import { TypingDots } from "../design/parts";
import { ChangeCard } from "./ChangeCard";
import { Greeting } from "./Greeting";
import { MAX_IMAGES, imageFiles } from "../api/uploads";
import { Composer } from "./Composer";
import { Thumb, type PendingImage } from "./ImageStrip";
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
  const [images, setImages] = useState<PendingImage[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const counter = useRef(0);

  function addFiles(files: File[]) {
    if (files.length === 0) return;
    const room = MAX_IMAGES - images.length;
    setNotice(files.length > room ? tr.chat.tooManyImages(MAX_IMAGES) : null);
    const added = files.slice(0, Math.max(room, 0)).map((file) => {
      counter.current += 1;
      return { id: `p${String(counter.current)}`, file, url: URL.createObjectURL(file) };
    });
    setImages((prev) => [...prev, ...added]);
  }

  function removeImage(id: string) {
    setImages((prev) => {
      const gone = prev.find((image) => image.id === id);
      if (gone) URL.revokeObjectURL(gone.url);
      return prev.filter((image) => image.id !== id);
    });
    setNotice(null);
  }

  const last = chat.items[chat.items.length - 1];
  const lastText = last?.kind === "assistant" ? last.text : "";
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [chat.items.length, lastText]);

  function send() {
    const text = draft;
    const files = images;
    setDraft("");
    setImages([]); // the previews live on in the sent bubble
    setNotice(null);
    void chat.send(text, "chat", files);
  }

  return (
    <div
      className="relative flex h-full flex-col"
      onDragOver={(event) => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) setDragging(false);
      }}
      onDrop={(event) => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        setDragging(false);
        addFiles(imageFiles(event.dataTransfer.files));
      }}
    >
      {dragging && (
        <div className="pointer-events-none absolute inset-2 z-10 flex items-center justify-center rounded-3xl border-2 border-dashed border-indigo-400 bg-indigo-50/80 text-indigo-700 dark:bg-indigo-950/70 dark:text-indigo-200">
          {tr.chat.dropHere}
        </div>
      )}
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
          <Empty onPick={setDraft} team={chat.team} />
        ) : (
          <ul className="mx-auto flex max-w-2xl flex-col gap-5">
            <li className="pb-1 pt-2">
              <Greeting team={chat.team} />
            </li>
            {chat.items.map((item) =>
              item.kind === "user" ? (
                <li key={item.id} className="yv-rise flex flex-col items-end gap-1">
                  {item.images.length > 0 && (
                    <div className="flex max-w-[85%] flex-wrap justify-end gap-1">
                      {item.images.map((image) => (
                        <a key={image.url} href={image.url} target="_blank" rel="noreferrer">
                          <Thumb url={image.url} name={image.name} className="h-28 w-28 sm:h-36 sm:w-36" />
                        </a>
                      ))}
                    </div>
                  )}
                  {item.text && (
                    <p className="max-w-[85%] whitespace-pre-wrap rounded-3xl rounded-br-lg bg-gradient-to-br from-indigo-500 to-violet-600 px-4 py-2.5 text-white shadow-[0_10px_30px_-14px_rgba(99,102,241,0.8)]">
                      {item.text}
                    </p>
                  )}
                </li>
              ) : (
                <Answer
                  key={item.id}
                  item={item}
                  members={members}
                  undo={chat.undo}
                  onUndo={(changeSetId) => void chat.undoChange(item.id, changeSetId)}
                  quickReplies={
                    item.origin === "checkin" && item.id === last?.id && !chat.busy
                      ? {
                          onAllDone: () => void chat.send(tr.chat.allDone),
                          onEdit: () => {
                            setDraft(tr.chat.editPrefix);
                            document.querySelector<HTMLTextAreaElement>("form textarea")?.focus();
                          },
                        }
                      : undefined
                  }
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
      {notice && (
        <p className="px-3 pb-1 text-center text-xs text-amber-700 dark:text-amber-400" role="status">
          {notice}
        </p>
      )}
      <Composer
        value={draft}
        onChange={setDraft}
        onSend={send}
        busy={chat.busy}
        images={images}
        onAddFiles={addFiles}
        onRemoveImage={removeImage}
      />
    </div>
  );
}

function Answer({
  item,
  members,
  undo,
  onUndo,
  quickReplies,
}: {
  item: AssistantItem;
  members: Record<string, Member>;
  undo: UndoState;
  onUndo: (changeSetId: string) => void;
  quickReplies?: { onAllDone: () => void; onEdit: () => void };
}) {
  const speaker = item.speaker ? members[item.speaker] : undefined;
  const color = speaker?.color ?? "#6366f1";
  // A yaver's answer is plain text next to its orb (no bubble): the name in its colour,
  // then the words, then what it did.
  return (
    <li className="yv-rise flex gap-3">
      <span className="pt-0.5">
        <YaverAvatar member={speaker} id={item.speaker ?? undefined} size={32} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-grotesk text-[0.8rem] font-semibold tracking-wide" style={{ color }}>
          {speaker?.name ?? tr.appName}
          {item.origin && (
            <span className="ml-2 rounded-full bg-slate-900/5 px-2 py-0.5 font-sans text-[0.7rem] font-medium text-slate-500 dark:bg-white/10 dark:text-slate-300">
              {tr.chat.origin[item.origin]}
            </span>
          )}
        </p>
        <div className="mt-0.5 text-[0.97rem] leading-relaxed">
          {item.text ? (
            <Markdown text={item.text} />
          ) : item.streaming ? (
            <div className="py-2">
              <TypingDots color={color} />
            </div>
          ) : null}
        </div>
        {item.status && item.streaming && (
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-300" role="status">
            {item.status.code === "reading_images"
              ? tr.chat.readingImages(item.status.count)
              : tr.chat.waiting(item.status.provider)}
          </p>
        )}
        {item.error && (
          <p className="text-sm text-rose-600 dark:text-rose-400">
            {tr.chat.errors[item.error] ?? tr.chat.errors.internal}
          </p>
        )}
        {quickReplies && (
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={quickReplies.onAllDone}
              className="min-h-10 rounded-full bg-gradient-to-br from-emerald-500 to-teal-600 px-4 text-sm font-medium text-white shadow-[0_8px_20px_-10px_rgba(16,185,129,0.9)] hover:brightness-110"
            >
              {tr.chat.allDone}
            </button>
            <button
              type="button"
              onClick={quickReplies.onEdit}
              className="yv-glass min-h-10 rounded-full px-4 text-sm font-medium"
            >
              {tr.chat.edit}
            </button>
          </div>
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
      <ul className="yv-glass space-y-1.5 rounded-3xl p-4 text-sm">
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

function Empty({ onPick, team }: { onPick: (text: string) => void; team: Team | undefined }) {
  return (
    <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center gap-5 text-center">
      <Greeting team={team} large />
      <p className="yv-rise text-sm text-slate-600 dark:text-slate-300" style={{ animationDelay: "120ms" }}>
        {tr.chat.emptyHint}
      </p>
      <div className="flex flex-wrap justify-center gap-2">
        {tr.chat.examples.map((example, index) => (
          <button
            key={example}
            type="button"
            onClick={() => {
              onPick(example);
            }}
            className="yv-glass yv-rise rounded-full px-3.5 py-2 text-sm text-slate-700 hover:bg-white/80 dark:text-slate-200 dark:hover:bg-white/10"
            style={{ animationDelay: `${String(200 + index * 70)}ms` }}
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}
