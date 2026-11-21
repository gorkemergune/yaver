import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

import { apiGet } from "../api/client";
import type { EmployeeNote, EmployeeTask, OfficeEmployee } from "../api/types";
import { XIcon } from "../components/icons";
import { tr } from "../i18n/tr";
import { deskCenter, SCENE_H, SCENE_W } from "./geometry";
import { officeKeys } from "./useOffice";

const t = tr.office.screen;
const hm = (iso: string | null): string =>
  iso ? new Date(iso).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" }) : "";

interface Props {
  employee: OfficeEmployee;
  status: string; // what the scene says it is doing (figureView)
  onClose: () => void;
}

/**
 * Clicking a desk zooms into its screen (O5): what the employee is working on right now,
 * from the same backend state as the scene (task, tool, since), the job in its inbox and
 * the last notebook lines. Off: the screen is dark. Grows out of the desk.
 */
export function DeskScreen({ employee: e, status, onClose }: Props) {
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
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    close.current?.focus();
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const dark = e.activity === "off";
  const busy = e.activity === "working" || e.activity === "meeting";
  const running = tasks.data?.tasks.find((task) => task.status === "running");
  const lastDone = tasks.data?.tasks.find((task) => task.status !== "running");
  const center = deskCenter(e.desk.row, e.desk.col);
  const origin = { "--yhq-origin": `${String((center.X / SCENE_W) * 100)}% ${String((center.Y / SCENE_H) * 100)}%` } as CSSProperties;

  return (
    <div
      className="yhq-screen-backdrop"
      style={{ zIndex: 950 }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="yhq-screen" style={origin} role="dialog" aria-modal="true" aria-label={t.label(e.name)} data-screen={e.id}>
        <div className="yhq-screen-glass" data-dark={dark} style={{ "--yhq-accent": e.color } as CSSProperties}>
          <div className="flex items-center gap-2 border-b border-white/10 pb-2">
            <span className={`h-2 w-2 flex-none rounded-full ${dark ? "bg-slate-600" : busy ? "yhq-glow bg-[#3ddc97]" : "bg-amber-300"}`} />
            <span className="truncate font-grotesk text-base font-bold" style={{ color: e.color }}>
              {e.name}
            </span>
            <span className="truncate text-xs text-white/50">{e.role}</span>
            <button
              ref={close}
              type="button"
              onClick={onClose}
              aria-label={t.close}
              className="ml-auto flex h-9 w-9 flex-none items-center justify-center rounded-lg text-white/70 hover:bg-white/10"
            >
              <XIcon width={14} height={14} />
            </button>
          </div>
          {dark ? (
            <p className="py-10 text-center font-mono text-sm text-white/40">{t.dark}</p>
          ) : (
            <div className="flex flex-col gap-3 pt-3 font-mono text-[13px] leading-snug text-white/85">
              <p className="text-[15px] text-white">
                <span style={{ color: e.color }}>›</span> {busy ? status : t.idle}
              </p>
              {busy && (
                <p className="text-xs text-white/50">
                  {e.tool ? `${t.tool}: ${e.tool} · ` : ""}
                  {t.since(hm(e.since))}
                </p>
              )}
              {running && (
                <Block title={t.running}>
                  <p>{running.instruction}</p>
                </Block>
              )}
              {!running && lastDone && (
                <Block title={t.lastDone}>
                  <p>{lastDone.instruction}</p>
                  {lastDone.result && <p className="mt-1 line-clamp-3 text-white/55">{lastDone.result}</p>}
                </Block>
              )}
            </div>
          )}
          {notes.data?.notes.length ? (
            <Block title={t.notes}>
              {notes.data.notes.slice(0, 2).map((n) => (
                <p key={n.id} className="line-clamp-2 text-white/70">
                  <span className="text-white/40">{hm(n.created_at)}</span> {n.content}
                </p>
              ))}
            </Block>
          ) : null}
        </div>
        <div className="yhq-screen-stand" />
      </div>
    </div>
  );
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mt-3 flex flex-col gap-1 font-mono text-[12.5px]">
      <span className="text-[10.5px] uppercase tracking-[0.1em] text-white/40">{title}</span>
      {children}
    </div>
  );
}
