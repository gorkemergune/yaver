import "@fontsource-variable/fraunces";
import "@fontsource-variable/space-grotesk";
import "./design.css";

import { useMemo, useState, type ReactNode } from "react";

import { useTeam } from "../api/queries";
import { tr } from "../i18n/tr";
import { DEFAULT_MEMBERS, type PreviewMember, type Role } from "./mock";
import { Aurora, Ember, type VariantProps } from "./variants";

type Show = "a" | "b" | "both";

const VARIANTS: { id: "a" | "b"; title: string; note: string; render: (p: VariantProps) => ReactNode }[] = [
  { id: "a", title: tr.design.aTitle, note: tr.design.aNote, render: (p) => <Aurora {...p} /> },
  { id: "b", title: tr.design.bTitle, note: tr.design.bNote, render: (p) => <Ember {...p} /> },
];

/** /design-preview: two directions for the redesign, with mock content, to pick from. */
export function DesignPreview() {
  const team = useTeam();
  const params = new URLSearchParams(window.location.search);
  const [show, setShow] = useState<Show>(() => {
    const asked = params.get("show");
    if (asked === "a" || asked === "b" || asked === "both") return asked;
    return window.matchMedia("(min-width: 900px)").matches ? "both" : "a";
  });
  const [dark, setDark] = useState(params.get("theme") !== "light"); // ?theme=light&show=a
  const [replay, setReplay] = useState(0);

  // Real yaver names and colours when the API answers; the sample team otherwise.
  const members = useMemo<Record<Role, PreviewMember>>(() => {
    const byRole = Object.fromEntries(DEFAULT_MEMBERS.map((m) => [m.role, m])) as Record<Role, PreviewMember>;
    if (!team.data) return byRole;
    const real = [team.data.coordinator, ...team.data.agents];
    for (const member of DEFAULT_MEMBERS) {
      const found = real.find((m) => m.id === member.id);
      if (found) byRole[member.role] = { ...member, name: found.name, color: found.color };
    }
    return byRole;
  }, [team.data]);
  const configured = team.data?.user_name ?? "";
  const userName = configured.length > 0 ? configured : "Görkem";

  const visible = VARIANTS.filter((v) => show === "both" || v.id === show);

  return (
    <div className="min-h-dvh overflow-x-hidden bg-neutral-950 text-neutral-100">
      <header className="sticky top-0 z-20 border-b border-white/10 bg-neutral-950/85 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3">
          <a href="#/chat" className="text-sm text-neutral-400 hover:text-white">
            ← {tr.appName}
          </a>
          <h1 className="text-base font-semibold">{tr.design.title}</h1>
          <div className="-mx-4 flex w-[calc(100%+2rem)] items-center gap-2 overflow-x-auto px-4 sm:mx-0 sm:ml-auto sm:w-auto sm:overflow-visible sm:px-0">
            <Segmented
              value={show}
              onChange={setShow}
              options={[
                ["a", "A"],
                ["b", "B"],
                ["both", tr.design.both],
              ]}
            />
            <Segmented
              value={dark ? "dark" : "light"}
              onChange={(v) => {
                setDark(v === "dark");
              }}
              options={[
                ["dark", tr.design.dark],
                ["light", tr.design.light],
              ]}
            />
            <button
              type="button"
              onClick={() => {
                setReplay((n) => n + 1);
              }}
              className="min-h-9 shrink-0 whitespace-nowrap rounded-full border border-white/15 px-3 text-sm hover:bg-white/10"
            >
              {tr.design.replay}
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-wrap justify-center gap-8 px-0 py-6 sm:px-4">
        {visible.map((variant) => (
          <section key={`${variant.id}-${String(replay)}-${String(dark)}`} className="w-full min-w-0 max-w-[400px]">
            <div className="mb-3 px-4 sm:px-0">
              <h2 className="text-lg font-semibold">{variant.title}</h2>
              <p className="text-sm text-neutral-400">{variant.note}</p>
            </div>
            {/* phone frame on wide screens, full width on a phone */}
            <div className="h-[calc(100dvh-9rem)] max-h-[800px] min-h-[640px] overflow-hidden sm:rounded-[2.6rem] sm:border sm:border-white/15 sm:shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)]">
              {variant.render({ dark, userName, members, tab: params.get("tab") === "today" ? "today" : "chat" })}
            </div>
          </section>
        ))}
      </main>
      <p className="pb-8 text-center text-sm text-neutral-400">{tr.design.pick}</p>
    </div>
  );
}

function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div className="inline-flex shrink-0 rounded-full border border-white/15 p-0.5">
      {options.map(([key, label]) => (
        <button
          key={key}
          type="button"
          aria-pressed={value === key}
          onClick={() => {
            onChange(key);
          }}
          className={`min-h-8 rounded-full px-3 text-sm transition-colors ${value === key ? "bg-white text-neutral-900" : "text-neutral-300 hover:text-white"}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
