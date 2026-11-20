import { Fragment, useState } from "react";

import { useDayPlan } from "../api/queries";
import type { DayAttendance, DayPlan, PlanItem } from "../api/types";
import { tr } from "../i18n/tr";
import { shortDate } from "../lib/changes";
import { toMinutes, useNowMinutes } from "../design/time";
import { detailLines } from "./details";
import { kindColor } from "./kinds";
import { movedTo } from "./week";

export function DayView({ offset }: { offset: 0 | 1 }) {
  const plan = useDayPlan(offset);
  if (plan.isPending) return <Notice text={tr.plan.loading} />;
  if (plan.isError) return <Notice text={tr.plan.error} />;
  return (
    <div className="mx-auto max-w-2xl px-3 py-4">
      <DayCard day={plan.data} today={plan.data.today} expanded />
    </div>
  );
}

export function Notice({ text }: { text: string }) {
  return <p className="p-6 text-center text-sm text-slate-500 dark:text-slate-400">{text}</p>;
}

/** One day: holidays, all-day items, timeline, cancellations, conflicts, tasks. */
export function DayCard({ day, today, expanded = false }: { day: DayPlan; today: string; expanded?: boolean }) {
  const isToday = day.date === today;
  const allDay = day.items.filter((item) => item.all_day);
  const timed = day.items.filter((item) => !item.all_day);
  const empty =
    day.items.length === 0 && !day.cancelled?.length && !day.moved_away?.length && !day.attendance?.length && !day.tasks?.length;
  // absences on a class shown on that class; the rest (block gone) as their own lines
  const absenceOf = (item: PlanItem): DayAttendance | undefined =>
    item.type === "block" ? day.attendance?.find((a) => a.block_id === item.id) : undefined;
  const loose = day.attendance?.filter((a) => !timed.some((item) => absenceOf(item) === a)) ?? [];
  const nowMinutes = useNowMinutes();
  // the line goes before the first item that has not started yet
  const nowIndex = (() => {
    const found = timed.findIndex((item) => toMinutes(item.start ?? "00:00") > nowMinutes);
    return found === -1 ? timed.length : found;
  })();
  return (
    <section
      className={`yv-glass yv-rise @container min-w-0 rounded-3xl ${expanded ? "p-4" : "p-3"} ${
        isToday ? "ring-2 ring-indigo-400/50 dark:ring-indigo-400/40" : ""
      }`}
    >
      <header className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className={`font-grotesk tracking-tight ${expanded ? "text-2xl font-semibold" : "font-semibold"}`}>
          {day.weekday}{" "}
          <span className="font-normal text-slate-500 dark:text-slate-400">{shortDate(day.date).replace(/\s\S+$/, "")}</span>
        </h2>
        {isToday && <span className="text-xs font-medium text-indigo-600 dark:text-indigo-400">{tr.plan.today}</span>}
      </header>

      {day.holidays?.map((holiday) => (
        <p key={holiday} className="mb-2 rounded-lg bg-amber-50 px-3 py-1.5 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          {tr.plan.holiday}: {holiday}
        </p>
      ))}

      {allDay.length > 0 && (
        <div className="mb-2 space-y-1.5">
          {allDay.map((item) => (
            <AllDay key={`${item.type}-${String(item.id)}`} item={item} />
          ))}
        </div>
      )}

      {empty ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">{tr.plan.empty}</p>
      ) : (
        <ol className="space-y-1.5">
          {timed.map((item, index) => (
            <Fragment key={`${item.type}-${String(item.id)}`}>
              {isToday && expanded && nowIndex === index && <NowLine minutes={nowMinutes} />}
              <Row item={item} compact={!expanded} absence={absenceOf(item)} />
            </Fragment>
          ))}
          {isToday && expanded && timed.length > 0 && nowIndex === timed.length && <NowLine minutes={nowMinutes} />}
          {day.moved_away?.map((moved) => (
            <li
              key={`m-${String(moved.block_id)}`}
              className="flex flex-col text-sm text-slate-400 @[17rem]:flex-row @[17rem]:gap-3 dark:text-slate-500"
            >
              <span className="shrink-0 tabular-nums line-through @[17rem]:w-12">{moved.start}</span>
              <span className="min-w-0 break-words">
                <span className="line-through">{moved.title}</span> → {movedTo(moved.moved_to, day.date)} ·{" "}
                {tr.plan.movedAway}
              </span>
            </li>
          ))}
          {loose.map((absence) => (
            <li key={`a-${absence.course}-${String(absence.block_id)}`} className="text-sm font-medium text-rose-600 dark:text-rose-400">
              <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-rose-500" aria-hidden />
              {tr.plan.absentCourse(absence.course, absence.hours)}
            </li>
          ))}
          {day.cancelled?.map((cancelled) => (
            <li
              key={`c-${String(cancelled.block_id)}`}
              className="flex flex-col text-sm text-slate-400 line-through @[17rem]:flex-row @[17rem]:gap-3"
            >
              <span className="shrink-0 tabular-nums @[17rem]:w-12">{cancelled.start}</span>
              <span className="min-w-0 break-words">
                {cancelled.title} · {tr.plan.cancelled}
                {cancelled.reason ? ` (${cancelled.reason})` : ""}
              </span>
            </li>
          ))}
        </ol>
      )}

      {day.conflicts?.map(([a, b]) => (
        <p key={`${a}-${b}`} className="mt-2 text-xs text-rose-600 dark:text-rose-400">
          ⚠ {tr.plan.conflict(a, b)}
        </p>
      ))}

      <Tasks title={tr.plan.tasks} tasks={day.tasks} compact={!expanded} />
      {expanded && <Tasks title={tr.plan.weekTasks} tasks={day.week_tasks} />}
    </section>
  );
}

/**
 * One timed item. The title wraps to two lines and the end time sits under the start, so
 * nothing is cut; a tap opens everything (full title, time range, place, note).
 * In a narrow card (7-column week) the times go above the title.
 */
function Row({ item, compact, absence }: { item: PlanItem; compact: boolean; absence?: DayAttendance }) {
  const [open, setOpen] = useState(false);
  const color = kindColor(item.kind);
  const missed = absence
    ? absence.status === "excused"
      ? tr.plan.excused(absence.hours)
      : tr.plan.absent(absence.hours)
    : null;
  return (
    <li className="flex flex-col gap-0.5 @[17rem]:flex-row @[17rem]:gap-3">
      <span className="flex shrink-0 gap-1 text-xs tabular-nums text-slate-500 @[17rem]:w-12 @[17rem]:flex-col @[17rem]:gap-0 @[17rem]:pt-1.5 @[17rem]:text-sm dark:text-slate-400">
        <span>{item.start ?? ""}</span>
        {item.end && (
          <span className="text-slate-400 @[17rem]:text-xs dark:text-slate-500">
            <span className="@[17rem]:hidden">– </span>
            {item.end}
          </span>
        )}
      </span>
      <button
        type="button"
        onClick={() => {
          setOpen((value) => !value);
        }}
        aria-expanded={open}
        title={open ? tr.plan.hideDetails : tr.plan.showDetails}
        className="min-w-0 flex-1 rounded-xl border-l-4 bg-white/55 px-3 py-1.5 text-left hover:bg-white/80 focus-visible:outline-2 focus-visible:outline-indigo-500 dark:bg-white/[0.045] dark:hover:bg-white/[0.08]"
        style={{ borderLeftColor: color }}
      >
        <span className={`block break-words font-medium leading-snug ${open ? "" : "line-clamp-2"}`}>{item.title}</span>
        {missed && (
          <span
            className={`mt-0.5 inline-flex items-center gap-1 rounded-full px-1.5 text-[0.7rem] font-semibold ${
              absence?.status === "excused"
                ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                : "bg-rose-500/15 text-rose-700 dark:text-rose-300"
            }`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
            {missed}
          </span>
        )}
        {!compact && !open && (
          <span className="block truncate text-xs text-slate-500 dark:text-slate-400">
            {tr.kinds[item.kind] ?? item.kind}
            {item.location ? ` · ${item.location}` : ""}
            {item.moved_from ? ` · ${tr.plan.moved(item.moved_from.slice(11))}` : ""}
          </span>
        )}
        {open && <Details item={item} />}
      </button>
    </li>
  );
}

function AllDay({ item }: { item: PlanItem }) {
  const [open, setOpen] = useState(false);
  const color = kindColor(item.kind);
  return (
    <button
      type="button"
      onClick={() => {
        setOpen((value) => !value);
      }}
      aria-expanded={open}
      className={`block max-w-full px-2.5 py-1 text-left text-xs font-medium ${open ? "w-full rounded-lg" : "rounded-2xl"}`}
      style={{ color, backgroundColor: `${color}1f` }}
    >
      <span className={`break-words ${open ? "" : "line-clamp-2"}`}>{item.title}</span>
      {open && <Details item={item} />}
    </button>
  );
}

/** Where "now" falls between today's items, with a pulsing dot. */
function NowLine({ minutes }: { minutes: number }) {
  const label = `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  return (
    <li className="flex items-center gap-2 py-0.5" aria-label={`${tr.plan.now} ${label}`}>
      <span className="w-12 shrink-0 text-right text-xs font-semibold tabular-nums text-pink-500">{label}</span>
      <span
        className="yv-pulse h-2.5 w-2.5 shrink-0 rounded-full bg-pink-500"
        style={{ ["--yv-pulse" as string]: "rgb(236 72 153 / 0.55)" }}
      />
      <span className="h-px flex-1 bg-gradient-to-r from-pink-500 to-pink-500/0" />
      <span className="rounded-full bg-pink-500 px-1.5 text-[0.65rem] font-semibold text-white">{tr.plan.now}</span>
    </li>
  );
}

function Details({ item }: { item: PlanItem }) {
  return (
    <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs font-normal text-slate-600 dark:text-slate-300">
      {detailLines(item).map((line) => (
        <Fragment key={line.label}>
          <dt className="text-slate-400 dark:text-slate-500">{line.label}</dt>
          <dd className="min-w-0 whitespace-pre-wrap break-words">{line.value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

/** Done ones struck through; `compact` (week cards): no heading, smaller. */
export function Tasks({ title, tasks, compact = false }: { title: string; tasks?: DayPlan["tasks"]; compact?: boolean }) {
  if (!tasks?.length) return null;
  return (
    <div className={compact ? "mt-2" : "mt-4"}>
      <h3 className={compact ? "sr-only" : "mb-1 text-sm font-medium text-slate-500 dark:text-slate-400"}>{title}</h3>
      <ul className={compact ? "space-y-0.5 text-xs text-slate-600 dark:text-slate-300" : "space-y-1 text-sm"}>
        {tasks.map((task) => (
          <li key={task.id} className={task.status === "done" ? "text-slate-400 line-through" : ""}>
            {task.status === "done" ? "☑" : "☐"} {task.title}
          </li>
        ))}
      </ul>
    </div>
  );
}
