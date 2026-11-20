import { useState, type ReactNode } from "react";

import { CHAT, DAY_END_HOUR, DAY_START_HOUR, TODAY, type Block, type PreviewMember, type Role } from "./mock";
import { Avatar, Rise, RoleIcon, TypingDots } from "./parts";
import { greeting, toMinutes, todayLabel, useNowMinutes } from "./time";

export interface VariantProps {
  dark: boolean;
  userName: string;
  members: Record<Role, PreviewMember>;
  tab?: Tab;
  plainAnswers?: boolean; // the applied design: A, with B's answers (no bubbles)
}

export type Tab = "chat" | "today";

/* ======================================================================================
   A · Aurora - cool night sky: drifting colour fields behind frosted glass, geometric
   type (Space Grotesk), glowing orb avatars, a floating glass tab bar.
   ====================================================================================== */

export function Aurora({ dark, userName, members, tab: initialTab = "chat", plainAnswers = false }: VariantProps) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const minutes = useNowMinutes();
  const t = dark
    ? {
        page: "bg-[#060914] text-slate-100",
        blobs: ["bg-indigo-600/45", "bg-fuchsia-600/30", "bg-cyan-500/30"],
        glass: "bg-white/[0.06] border-white/10 shadow-[0_8px_30px_-12px_rgba(0,0,0,0.6)]",
        muted: "text-slate-400",
        soft: "text-slate-300",
        user: "bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-[0_10px_30px_-12px_rgba(99,102,241,0.8)]",
        chip: "bg-white/10 text-slate-200",
        nav: "bg-slate-900/55 border-white/10",
        navOn: "bg-white/15 text-white",
        line: "border-white/10",
      }
    : {
        page: "bg-[#eef2ff] text-slate-900",
        blobs: ["bg-indigo-300/60", "bg-pink-300/45", "bg-cyan-300/50"],
        glass: "bg-white/60 border-white/80 shadow-[0_10px_30px_-16px_rgba(30,41,99,0.35)]",
        muted: "text-slate-500",
        soft: "text-slate-600",
        user: "bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-[0_10px_30px_-14px_rgba(99,102,241,0.7)]",
        chip: "bg-indigo-50 text-indigo-700",
        nav: "bg-white/70 border-white/90",
        navOn: "bg-indigo-600 text-white",
        line: "border-slate-900/10",
      };

  return (
    <div className={`relative isolate flex h-full flex-col overflow-hidden font-sans ${t.page}`}>
      {/* drifting colour fields */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className={`yv-drift absolute -left-24 -top-24 h-72 w-72 rounded-full blur-3xl ${t.blobs[0] ?? ""}`} />
        <div className={`yv-drift absolute -right-20 top-40 h-64 w-64 rounded-full blur-3xl ${t.blobs[1] ?? ""}`} style={{ animationDelay: "-6s" }} />
        <div className={`yv-drift absolute -bottom-24 left-10 h-72 w-72 rounded-full blur-3xl ${t.blobs[2] ?? ""}`} style={{ animationDelay: "-12s" }} />
      </div>

      <header className="px-5 pb-3 pt-6">
        <Rise index={0}>
          <p className={`text-xs font-medium uppercase tracking-[0.18em] ${t.muted}`}>{todayLabel()}</p>
          <h1 className="font-grotesk mt-1 text-[2rem] font-semibold leading-[1.05] tracking-tight">
            {greeting(minutes)},{" "}
            <span className="bg-gradient-to-r from-indigo-400 via-fuchsia-400 to-cyan-300 bg-clip-text text-transparent">
              {userName}
            </span>
          </h1>
        </Rise>
        <Rise index={1} className="mt-3 flex flex-wrap gap-1.5">
          {(["academic", "agenda", "discipline"] as Role[]).map((role) => (
            <span key={role} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs backdrop-blur-xl ${t.glass}`}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: members[role].color }} />
              {members[role].name}
              <span className={t.muted}>{role === "academic" ? "1 ders" : role === "agenda" ? "1 toplantı" : "spor 19:00"}</span>
            </span>
          ))}
        </Rise>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-28">
        {tab === "chat" ? (
          <ul className="flex flex-col gap-3">
            {CHAT.map((line, i) => (
              <Rise key={i} index={i + 2}>
                {line.kind === "user" ? (
                  <p className={`ml-auto w-fit max-w-[82%] rounded-3xl rounded-br-lg px-4 py-2.5 text-[0.95rem] ${t.user}`}>{line.text}</p>
                ) : (
                  plainAnswers ? (
                    <PlainLine line={line} members={members} t={t} />
                  ) : (
                    <AuroraLine line={line} members={members} t={t} />
                  )
                )}
              </Rise>
            ))}
          </ul>
        ) : (
          <Timeline
            minutes={minutes}
            members={members}
            renderBlock={(block, member) => (
              <div
                className={`h-full overflow-hidden rounded-2xl border px-3 py-2 backdrop-blur-xl ${t.glass} ${block.cancelled ? "opacity-50" : ""}`}
                style={{ boxShadow: `inset 3px 0 0 ${member.color}` }}
              >
                <p className={`font-grotesk text-sm font-semibold ${block.cancelled ? "line-through" : ""}`}>{block.title}</p>
                <p className={`text-xs ${t.muted}`}>
                  {block.start}-{block.end} · {block.place}
                </p>
              </div>
            )}
            hourClass={`text-[0.7rem] ${t.muted}`}
            lineClass={t.line}
            nowColor="#f472b6"
          />
        )}
      </div>

      <nav className={`absolute inset-x-6 bottom-5 flex items-center justify-between gap-1 rounded-full border p-1.5 backdrop-blur-2xl ${t.nav}`}>
        <TabButton active={tab === "chat"} onClick={() => {
            setTab("chat");
          }} on={t.navOn} off={t.soft}>
          Sohbet
        </TabButton>
        <TabButton active={tab === "today"} onClick={() => {
            setTab("today");
          }} on={t.navOn} off={t.soft}>
          Bugün
        </TabButton>
        <span className={`px-3 text-xs ${t.muted}`}>Hafta</span>
      </nav>
    </div>
  );
}

function AuroraLine({
  line,
  members,
  t,
}: {
  line: Exclude<(typeof CHAT)[number], { kind: "user" }>;
  members: Record<Role, PreviewMember>;
  t: { glass: string; muted: string; chip: string };
}) {
  const member = members[line.member];
  return (
    <div className="flex items-end gap-2.5">
      <Avatar member={member} shape="orb" size={32} />
      <div className={`max-w-[84%] rounded-3xl rounded-bl-lg border px-4 py-2.5 backdrop-blur-xl ${t.glass}`}>
        <p className="font-grotesk text-xs font-semibold" style={{ color: member.color }}>
          {member.name}
        </p>
        {line.kind === "typing" ? (
          <div className="py-1.5">
            <TypingDots color={member.color} />
          </div>
        ) : (
          <>
            <p className="text-[0.95rem] leading-snug">
              {sentence(line.text)}
            </p>
            {line.change && (
              <p className={`mt-2 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${t.chip}`}>
                <span aria-hidden>↺</span> {line.change}
                <span className="whitespace-nowrap font-semibold">· Geri al</span>
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/** The applied design: A's orb, B's plain text (no bubble). */
function PlainLine({
  line,
  members,
  t,
}: {
  line: Exclude<(typeof CHAT)[number], { kind: "user" }>;
  members: Record<Role, PreviewMember>;
  t: { muted: string; chip: string };
}) {
  const member = members[line.member];
  return (
    <div className="flex gap-3">
      <Avatar member={member} shape="orb" size={32} />
      <div className="min-w-0 flex-1">
        <p className="font-grotesk text-[0.8rem] font-semibold tracking-wide" style={{ color: member.color }}>
          {member.name}
        </p>
        {line.kind === "typing" ? (
          <div className="py-2">
            <TypingDots color={member.color} />
          </div>
        ) : (
          <>
            <p className="mt-0.5 text-[0.97rem] leading-relaxed">{sentence(line.text)}</p>
            {line.change && (
              <p className={`mt-2 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs ${t.chip}`}>
                <span aria-hidden>↺</span> {line.change}
                <span className="whitespace-nowrap font-semibold">· Geri al</span>
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ======================================================================================
   B · Kor (Ember) - warm editorial: charcoal-to-plum dusk with film grain, a serif
   greeting (Fraunces), squircle icon tiles, text answers without bubbles.
   ====================================================================================== */

export function Ember({ dark, userName, members, tab: initialTab = "chat" }: VariantProps) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const minutes = useNowMinutes();
  const t = dark
    ? {
        page: "bg-gradient-to-b from-[#16100e] via-[#1b1214] to-[#241420] text-[#f6ede6]",
        glow: "bg-orange-500/25",
        card: "bg-[#2a1d1b]/70 border-[#f6ede6]/[0.08]",
        muted: "text-[#b9a69b]",
        user: "bg-[#f3b27a] text-[#2a1710]",
        accent: "text-[#f3b27a]",
        chip: "border-[#f3b27a]/30 text-[#f3b27a]",
        nav: "bg-[#1d1413]/90 border-[#f6ede6]/[0.08]",
        navOn: "bg-[#f6ede6] text-[#1b1214]",
        line: "border-[#f6ede6]/[0.08]",
      }
    : {
        page: "bg-gradient-to-b from-[#fbf6ef] via-[#f8efe6] to-[#f3e6e9] text-[#2b1d17]",
        glow: "bg-orange-300/40",
        card: "bg-white/75 border-[#2b1d17]/[0.08]",
        muted: "text-[#8a7366]",
        user: "bg-[#2b1d17] text-[#fbf6ef]",
        accent: "text-[#c2410c]",
        chip: "border-[#c2410c]/30 text-[#c2410c]",
        nav: "bg-white/85 border-[#2b1d17]/[0.08]",
        navOn: "bg-[#2b1d17] text-[#fbf6ef]",
        line: "border-[#2b1d17]/[0.08]",
      };

  return (
    <div className={`yv-grain relative isolate flex h-full flex-col overflow-hidden font-sans ${t.page}`}>
      <div aria-hidden className={`yv-drift pointer-events-none absolute -right-28 -top-28 -z-10 h-80 w-80 rounded-full blur-3xl ${t.glow}`} />

      <header className="px-6 pb-4 pt-7">
        <Rise index={0}>
          <h1 className="font-fraunces text-[2.35rem] font-light leading-[1.02] tracking-tight">
            <span className="italic">{greeting(minutes)},</span>
            <br />
            <span className="font-semibold">{userName}.</span>
          </h1>
        </Rise>
        <Rise index={1}>
          <p className={`mt-3 text-sm ${t.muted}`}>
            {todayLabel()} · <span className={t.accent}>3 plan</span>, ilki 13:00 Fizik II
          </p>
        </Rise>
        <Rise index={2} className="mt-4 flex gap-2">
          {(["coordinator", "academic", "agenda", "discipline"] as Role[]).map((role) => (
            <Avatar key={role} member={members[role]} shape="tile" size={40} />
          ))}
        </Rise>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-24">
        {tab === "chat" ? (
          <ul className="flex flex-col gap-5">
            {CHAT.map((line, i) => (
              <Rise key={i} index={i + 3}>
                {line.kind === "user" ? (
                  <p className={`ml-auto w-fit max-w-[80%] rounded-[1.4rem] rounded-tr-md px-4 py-2.5 text-[0.95rem] ${t.user}`}>{line.text}</p>
                ) : (
                  <EmberLine line={line} members={members} t={t} />
                )}
              </Rise>
            ))}
          </ul>
        ) : (
          <Timeline
            minutes={minutes}
            members={members}
            renderBlock={(block, member) => (
              <div className={`flex h-full gap-2.5 overflow-hidden rounded-[1.25rem] border px-3 py-2 ${t.card} ${block.cancelled ? "opacity-50" : ""}`}>
                <span className="mt-0.5" style={{ color: member.color }}>
                  <RoleIcon role={member.role} size={16} />
                </span>
                <div>
                  <p className={`font-fraunces text-[0.95rem] font-semibold ${block.cancelled ? "line-through" : ""}`}>{block.title}</p>
                  <p className={`text-xs ${t.muted}`}>
                    {block.start}-{block.end} · {block.place}
                  </p>
                </div>
              </div>
            )}
            hourClass={`font-fraunces text-[0.75rem] italic ${t.muted}`}
            lineClass={t.line}
            nowColor="#fb7185"
          />
        )}
      </div>

      <nav className={`absolute inset-x-0 bottom-0 flex items-center gap-2 border-t px-5 pb-5 pt-3 ${t.nav}`}>
        <TabButton active={tab === "chat"} onClick={() => {
            setTab("chat");
          }} on={t.navOn} off={t.muted}>
          Sohbet
        </TabButton>
        <TabButton active={tab === "today"} onClick={() => {
            setTab("today");
          }} on={t.navOn} off={t.muted}>
          Bugün
        </TabButton>
        <span className={`ml-auto font-fraunces text-sm italic ${t.muted}`}>yaver</span>
      </nav>
    </div>
  );
}

function EmberLine({
  line,
  members,
  t,
}: {
  line: Exclude<(typeof CHAT)[number], { kind: "user" }>;
  members: Record<Role, PreviewMember>;
  t: { muted: string; chip: string };
}) {
  const member = members[line.member];
  return (
    <div className="flex gap-3">
      <Avatar member={member} shape="tile" size={30} />
      <div className="min-w-0 flex-1 pt-0.5">
        <p className="text-[0.78rem] font-semibold tracking-[0.04em]" style={{ color: member.color }}>
          {member.name}
        </p>
        {line.kind === "typing" ? (
          <div className="py-2">
            <TypingDots color={member.color} />
          </div>
        ) : (
          <>
            <p className="mt-0.5 text-[0.98rem] leading-relaxed">
              {sentence(line.text)}
            </p>
            {line.change && (
              <p className={`mt-2 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs ${t.chip}`}>
                {line.change} <span className="whitespace-nowrap font-semibold">· Geri al</span>
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* --- shared --------------------------------------------------------------------------- */

function sentence(text: string): string {
  return text.charAt(0).toLocaleUpperCase("tr") + text.slice(1);
}

function TabButton({ active, onClick, on, off, children }: { active: boolean; onClick: () => void; on: string; off: string; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`min-h-9 rounded-full px-4 text-sm font-medium transition-colors duration-300 ${active ? on : off}`}
    >
      {children}
    </button>
  );
}

const PX_PER_MIN = 1.1;

/** Today as a time axis; the "şu an" line moves with the clock. */
function Timeline({
  minutes,
  members,
  renderBlock,
  hourClass,
  lineClass,
  nowColor,
}: {
  minutes: number;
  members: Record<Role, PreviewMember>;
  renderBlock: (block: Block, member: PreviewMember) => ReactNode;
  hourClass: string;
  lineClass: string;
  nowColor: string;
}) {
  const start = DAY_START_HOUR * 60;
  const end = DAY_END_HOUR * 60;
  const height = (end - start) * PX_PER_MIN;
  const sample = minutes < start || minutes > end; // night: show the line at a sample time
  const now = sample ? 14 * 60 + 10 : minutes;
  const hours = Array.from({ length: DAY_END_HOUR - DAY_START_HOUR + 1 }, (_, i) => DAY_START_HOUR + i);
  return (
    <div className="relative mt-1" style={{ height }}>
      {hours.map((hour) => (
        <div key={hour} className={`absolute inset-x-0 flex items-start gap-2 border-t ${lineClass}`} style={{ top: (hour * 60 - start) * PX_PER_MIN }}>
          <span className={`-mt-2 w-10 shrink-0 ${hourClass}`}>{String(hour).padStart(2, "0")}:00</span>
        </div>
      ))}
      {TODAY.map((block, i) => {
        const top = (toMinutes(block.start) - start) * PX_PER_MIN;
        const blockHeight = Math.max((toMinutes(block.end) - toMinutes(block.start)) * PX_PER_MIN - 4, 40);
        return (
          <div key={block.title} className="absolute left-12 right-0" style={{ top: top + 2, height: blockHeight }}>
            <Rise index={i} className="h-full">
              {renderBlock(block, members[block.member])}
            </Rise>
          </div>
        );
      })}
      {(
        <div className="pointer-events-none absolute inset-x-0 z-10 flex items-center" style={{ top: (now - start) * PX_PER_MIN }} aria-label="şu an">
          <span
            className="yv-pulse ml-[2.6rem] h-2.5 w-2.5 -translate-y-1/2 rounded-full"
            style={{ background: nowColor, ["--yv-pulse" as string]: `${nowColor}88` }}
          />
          <span className="h-px flex-1 -translate-y-1/2" style={{ background: `linear-gradient(90deg, ${nowColor}, ${nowColor}00)` }} />
          <span className="-translate-y-1/2 rounded-full px-1.5 text-[0.65rem] font-semibold text-white" style={{ background: nowColor }}>
            {sample ? "şu an · örnek" : "şu an"}
          </span>
        </div>
      )}
    </div>
  );
}
