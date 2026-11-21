import { useQuery } from "@tanstack/react-query";
import { useState, type SubmitEvent } from "react";

import { apiGet } from "../api/client";
import type { EmployeeNote, EmployeeTask, Member, OfficeEmployee } from "../api/types";
import { Answer } from "../chat/ChatView";
import { XIcon } from "../components/icons";
import { tr } from "../i18n/tr";
import { money } from "../lib/format";
import { useEmployeeChat } from "./useEmployeeChat";
import { officeKeys } from "./useOffice";

const t = tr.office.panel;
const LABEL = "text-[11px] font-medium uppercase tracking-[0.08em] text-slate-500 dark:text-[#9aa2c9]";

function clock(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("tr-TR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

interface Props {
  employee: OfficeEmployee;
  status: string;
  members: Record<string, Member>;
  onClose: () => void;
}

export function EmployeePanel({ employee: e, status, members, onClose }: Props) {
  const notes = useQuery({
    queryKey: officeKeys.notes(e.id),
    queryFn: ({ signal }) =>
      apiGet<{ notes: EmployeeNote[] }>(`/employees/${encodeURIComponent(e.id)}/notes?limit=12`, { signal }),
  });
  const tasks = useQuery({
    queryKey: officeKeys.tasks(e.id),
    queryFn: ({ signal }) =>
      apiGet<{ tasks: EmployeeTask[] }>(`/employees/${encodeURIComponent(e.id)}/tasks?limit=6`, { signal }),
  });

  return (
    <section aria-label={e.name} className="yv-glass flex flex-col gap-4 rounded-[20px] p-5">
      <div className="flex items-center gap-3">
        <div
          className="flex h-12 w-12 flex-none items-center justify-center rounded-[14px] font-grotesk text-xl font-bold text-[#0b0f24]"
          style={{ background: e.color }}
        >
          {e.name.charAt(0)}
        </div>
        <div className="flex min-w-0 flex-auto flex-col">
          <span className="truncate font-grotesk text-xl font-bold" style={{ color: e.color }}>
            {e.name}
          </span>
          <span className="text-[13px] text-slate-500 dark:text-[#9aa2c9]">{e.role}</span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t.close}
          className="flex h-11 w-11 flex-none items-center justify-center rounded-xl border border-slate-300/70 text-slate-600 hover:bg-white/60 dark:border-[#262f5a] dark:text-[#c7cbe0] dark:hover:bg-white/5"
        >
          <XIcon width={16} height={16} />
        </button>
      </div>

      <div className="yv-inset flex flex-col gap-1.5 rounded-[14px] px-3.5 py-3">
        <span className={LABEL}>{t.now}</span>
        <span className="flex items-center gap-2 text-sm">
          {e.needs_user && <span className="h-1.5 w-1.5 flex-none rounded-full bg-[#ff6b6b]" />}
          {status}
        </span>
        {e.daily_budget_usd !== null && (
          <span className="text-xs text-slate-500 dark:text-[#9aa2c9]">
            {t.budget(money(String(e.spent_today_usd)), money(String(e.daily_budget_usd)))}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <span className={LABEL}>{t.notes}</span>
        {notes.data?.notes.length ? (
          notes.data.notes.map((n) => (
            <div key={n.id} className="yv-inset rounded-xl px-3 py-2.5 text-[13px] leading-snug">
              {n.content}
              <span className="mt-0.5 block text-[11px] text-slate-500 dark:text-[#9aa2c9]">{clock(n.created_at)}</span>
            </div>
          ))
        ) : (
          <p className="text-[13px] text-slate-500 dark:text-[#9aa2c9]">{notes.isPending ? "…" : t.notesEmpty}</p>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <span className={LABEL}>{t.inbox}</span>
        {tasks.data?.tasks.length ? (
          <ul className="flex flex-col gap-1.5">
            {tasks.data.tasks.map((task) => (
              <li key={task.id} className="flex gap-2 text-[13px] leading-snug">
                <span
                  className={`mt-1.5 h-1.5 w-1.5 flex-none rounded-full ${
                    task.status === "running" ? "bg-amber-400" : task.status === "done" ? "bg-emerald-400" : "bg-rose-400"
                  }`}
                  title={t.taskStatus[task.status]}
                />
                <span className="min-w-0">
                  <span className="text-slate-500 dark:text-[#9aa2c9]">{t.sources[task.source]} · </span>
                  {task.instruction}
                  <span className="block text-[11px] text-slate-500 dark:text-[#9aa2c9]">
                    {clock(task.started_at)} · {t.taskStatus[task.status]}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-slate-500 dark:text-[#9aa2c9]">{tasks.isPending ? "…" : t.inboxEmpty}</p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <span className={LABEL}>{t.shift}</span>
        <span className="text-[13px] leading-snug text-slate-700 dark:text-[#c7cbe0]">{e.shift || t.shiftEmpty}</span>
      </div>

      <DirectChat employee={e} members={members} />
    </section>
  );
}

function DirectChat({ employee: e, members }: { employee: OfficeEmployee; members: Record<string, Member> }) {
  const names = Object.fromEntries(Object.values(members).map((m) => [m.id, m.name]));
  const chat = useEmployeeChat(e.id, names);
  const [draft, setDraft] = useState("");
  const inputId = `ask-${e.id}`;

  function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.trim() || chat.busy) return;
    void chat.send(draft);
    setDraft("");
  }

  return (
    <div className="flex flex-col gap-2">
      <span className={LABEL}>{t.chat}</span>
      {chat.items.length === 0 ? (
        <p className="text-[13px] text-slate-500 dark:text-[#9aa2c9]">{t.chatEmpty}</p>
      ) : (
        <ul className="flex max-h-80 flex-col gap-3 overflow-y-auto pr-1">
          {chat.items.map((item) =>
            item.kind === "user" ? (
              <li key={item.id} className="self-end rounded-xl bg-indigo-500/90 px-3 py-2 text-[13px] text-white dark:bg-[#2a2f63]">
                {item.text}
              </li>
            ) : (
              <Answer
                key={item.id}
                item={item}
                members={members}
                undo={chat.undo}
                onUndo={(changeSetId) => void chat.undoChange(item.id, changeSetId)}
                onRetry={chat.busy ? undefined : () => {
                  chat.retry(item.id);
                }}
              />
            ),
          )}
        </ul>
      )}
      <form onSubmit={submit} className="flex gap-2">
        <label htmlFor={inputId} className="sr-only">
          {t.ask(e.name)}
        </label>
        <input
          id={inputId}
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
          placeholder={t.askPlaceholder(e.name)}
          className="h-11 min-w-0 flex-auto rounded-xl border border-slate-300/70 bg-white/70 px-3 text-sm outline-none focus:border-indigo-400 dark:border-[#262f5a] dark:bg-[#0c1126] dark:text-[#e8ebff]"
        />
        <button
          type="submit"
          disabled={chat.busy || !draft.trim()}
          className="h-11 rounded-xl px-3.5 text-[13px] font-bold text-[#0b0f24] disabled:opacity-50"
          style={{ background: e.color }}
        >
          {t.send}
        </button>
      </form>
    </div>
  );
}
