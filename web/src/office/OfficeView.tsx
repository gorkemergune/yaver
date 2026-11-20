import { useEffect, useMemo, useRef, useState } from "react";

import type { Member } from "../api/types";
import { MAX_IMAGES } from "../api/uploads";
import { Answer } from "../chat/ChatView";
import { Composer } from "../chat/Composer";
import type { PendingImage } from "../chat/ImageStrip";
import { useChat } from "../chat/useChat";
import { tr } from "../i18n/tr";
import { apiPost } from "../api/client";
import { href, useHashParam } from "../lib/route";
import { EmployeePanel } from "./EmployeePanel";
import type { AssistantItem } from "../chat/model";
import { figureView, isNight, type Staff } from "./model";
import { OfficeScene } from "./OfficeScene";
import { useFigures } from "./useFigures";
import { useOffice, type FeedItem } from "./useOffice";

function useHour(): number {
  const [hour, setHour] = useState(() => new Date().getHours());
  useEffect(() => {
    const timer = window.setInterval(() => {
      setHour(new Date().getHours());
    }, 60_000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);
  return hour;
}

const hm = (iso: string): string => new Date(iso).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });

/** The main screen (docs/OFFICE.md): the office scene, who is doing what, a panel per
 *  employee and "Yaver'e yaz" for the main chat. */
export function OfficeView() {
  const office = useOffice();
  const chat = useChat(); // the main conversation, shared with the Sohbet tab
  const figures = useFigures(office.staff);
  // in the URL (#/office?employee=academic): the task board opens a panel this way
  const [selected, setSelected] = useHashParam("employee");
  const night = isNight(useHour());
  const people = Object.values(office.staff);
  const members = useMemo<Record<string, Member>>(
    () => Object.fromEntries(people.map((e) => [e.id, { id: e.id, name: e.name, color: e.color, domain: e.domain }])),
    [people],
  );
  const chosen = selected ? office.staff[selected] : undefined;
  const chosenFigure = selected ? figures[selected] : undefined;
  const atDesk = people.filter((e) => {
    const f = figures[e.id];
    return f?.act === "work" && f.path.length === 0;
  }).length;

  return (
    <div className="mx-auto flex max-w-[1500px] flex-wrap gap-5 px-3 py-4 sm:px-6">
      <section aria-label={tr.office.title} className="flex min-w-0 flex-[999_1_640px] flex-col gap-3.5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="font-grotesk text-[26px] font-bold">{tr.office.title}</h1>
          <span className="text-[13px] text-slate-500 dark:text-[#9aa2c9]">{tr.office.hint}</span>
          <span className="ml-auto flex items-center gap-1.5 text-xs text-slate-500 dark:text-[#9aa2c9]" role="status">
            <span
              className={`h-2 w-2 rounded-full ${office.link === "live" ? "yhq-glow bg-[#3ddc97]" : "bg-amber-400"}`}
            />
            {office.link === "live"
              ? tr.office.atDesk(atDesk, people.length)
              : office.link === "connecting"
                ? tr.office.connecting
                : tr.office.reconnecting}
          </span>
        </div>
        {office.ready === false && (
          <p className="rounded-xl bg-amber-100 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/60 dark:text-amber-300">
            {tr.office.notReady}
          </p>
        )}
        <OfficeScene
          staff={office.staff}
          figures={figures}
          selected={selected}
          onSelect={(id) => {
            setSelected(selected === id ? null : id);
          }}
          night={night}
        />
        <MobileList staff={office.staff} figures={figures} selected={selected} onSelect={setSelected} />
        <MainComposer chat={chat} />
        {import.meta.env.DEV && <DevRituals />}
      </section>

      <aside aria-label={tr.office.panel.now} className="flex min-w-0 flex-[1_1_340px] flex-col gap-3.5 md:max-w-[460px]">
        {chosen && chosenFigure ? (
          <EmployeePanel
            key={chosen.id}
            employee={chosen}
            status={figureView(chosenFigure, chosen, office.staff).status}
            members={members}
            onClose={() => {
              setSelected(null);
            }}
          />
        ) : (
          <>
            <LastAnswer chat={chat} members={members} />
            <Feed feed={office.feed} staff={office.staff} />
          </>
        )}
      </aside>
    </div>
  );
}

/** Phones: the list under the scene (the scene scrolls sideways, the list would too). */
function MobileList({
  staff,
  figures,
  selected,
  onSelect,
}: {
  staff: Staff;
  figures: ReturnType<typeof useFigures>;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <ul className="yhq-mobile-list yv-glass grid-cols-1 gap-0.5 rounded-2xl p-1.5 min-[480px]:grid-cols-2" aria-label={tr.office.listLabel}>
      {Object.values(staff).map((e) => {
        const f = figures[e.id];
        return (
          <li key={e.id}>
            <button
              type="button"
              aria-pressed={selected === e.id}
              onClick={() => {
                onSelect(selected === e.id ? null : e.id);
              }}
              className={`flex min-h-10 w-full items-center gap-2 rounded-xl px-2.5 text-left text-[13px] ${selected === e.id ? "bg-indigo-500/15" : ""}`}
            >
              <span className="w-16 flex-none truncate font-bold" style={{ color: e.color }}>
                {e.name}
              </span>
              <span className="min-w-0 flex-auto truncate text-slate-600 dark:text-[#b9bfdc]">
                {f ? figureView(f, e, staff).status : ""}
              </span>
              {e.needs_user && <span className="yhq-alert" />}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/** "Yaver'e yaz": the main chat, the same conversation as the Sohbet tab. */
type Chat = ReturnType<typeof useChat>;

function MainComposer({ chat }: { chat: Chat }) {
  const [draft, setDraft] = useState("");
  const [images, setImages] = useState<PendingImage[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const counter = useRef(0);

  function send() {
    const text = draft;
    const files = images;
    setDraft("");
    setImages([]);
    setNotice(null);
    void chat.send(text, "chat", files);
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="px-1 text-[13px] font-bold text-indigo-600 dark:text-[#b3a6ff]">{tr.office.composerLabel}</span>
      <div>
        <Composer
          wide
          value={draft}
          onChange={setDraft}
          onSend={send}
          busy={chat.busy}
          images={images}
          onAddFiles={(files) => {
            const room = MAX_IMAGES - images.length;
            const added = files.slice(0, Math.max(room, 0)).map((file) => {
              counter.current += 1;
              return { id: `o${String(counter.current)}`, file, url: URL.createObjectURL(file) };
            });
            setImages((prev) => [...prev, ...added]);
          }}
          onRemoveImage={(id) => {
            setImages((prev) => prev.filter((image) => image.id !== id));
          }}
          onVoiceText={(text) => {
            setNotice(null);
            void chat.send(text, "chat", images);
            setImages([]);
          }}
          onVoiceError={(code) => {
            setNotice(tr.voice.errors[code] ?? tr.voice.errors.stt_unavailable ?? null);
          }}
        />
      </div>
      {notice && (
        <p className="px-1 text-xs text-amber-700 dark:text-amber-400" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}

/** Yaver's latest answer in the main chat, with its change card and "Geri al". */
function LastAnswer({ chat, members }: { chat: Chat; members: Record<string, Member> }) {
  const last = [...chat.items].reverse().find((item): item is AssistantItem => item.kind === "assistant");
  if (!last) return null;
  return (
    <section className="yv-glass flex flex-col gap-3 rounded-[20px] p-5" aria-label={tr.office.lastAnswer}>
      <div className="flex items-center justify-between">
        <span className="font-grotesk text-lg font-bold">{tr.office.lastAnswer}</span>
        <a href={href("chat")} className="text-xs text-indigo-600 hover:underline dark:text-[#a99cff]">
          {tr.office.openChat}
        </a>
      </div>
      <ul className="max-h-96 overflow-y-auto">
        <Answer
          item={last}
          members={members}
          undo={chat.undo}
          onUndo={(changeSetId) => void chat.undoChange(last.id, changeSetId)}
        />
      </ul>
    </section>
  );
}

function Feed({ feed, staff }: { feed: FeedItem[]; staff: Staff }) {
  return (
    <section className="yv-glass flex flex-col gap-3.5 rounded-[20px] p-5" aria-label={tr.office.feed.title}>
      <span className="font-grotesk text-lg font-bold">{tr.office.feed.title}</span>
      {feed.length === 0 ? (
        <p className="text-[13px] text-slate-500 dark:text-[#9aa2c9]">{tr.office.feed.empty}</p>
      ) : (
        feed.map((item) => {
          const who = staff[item.employeeId];
          const color = who?.color ?? "#9d8cff";
          return (
            <div key={item.id} className="flex flex-col gap-0.5 border-l-2 pl-2.5" style={{ borderColor: color }}>
              <span className="text-[13px] leading-snug">
                <span className="font-bold" style={{ color }}>
                  {who?.name ?? item.employeeId}
                </span>{" "}
                {item.text}
              </span>
              <span className="text-[11px] text-slate-500 dark:text-[#9aa2c9]">{hm(item.at)}</span>
            </div>
          );
        })
      )}
    </section>
  );
}

/** Development only (npm run dev): start a ritual now to watch it in the scene. It runs the
 *  real job (POST /api/jobs/{id}/run?force=true): real LLM calls, a real chat message. */
function DevRituals() {
  const [status, setStatus] = useState<string | null>(null);
  const rituals: [string, string][] = [
    ["briefing", tr.office.dev.standup],
    ["day_report", tr.office.dev.dayReport],
    ["weekly_plan", tr.office.dev.weekly],
  ];
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-amber-400/60 px-3 py-2 text-xs">
      <span className="font-medium text-amber-600 dark:text-amber-300">{tr.office.dev.label}</span>
      {rituals.map(([job, label]) => (
        <button
          key={job}
          type="button"
          className="rounded-full bg-amber-400/15 px-3 py-1 font-medium text-amber-700 hover:bg-amber-400/25 dark:text-amber-200"
          onClick={() => {
            setStatus(tr.office.dev.started(label));
            apiPost(`/jobs/${job}/run?force=true`).catch(() => {
              setStatus(tr.office.dev.failed);
            });
          }}
        >
          {label}
        </button>
      ))}
      {status && <span className="text-slate-500 dark:text-[#9aa2c9]">{status}</span>}
    </div>
  );
}
