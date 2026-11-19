import { Fragment, useState } from "react";

import { useDayPlan } from "../api/queries";
import type { DayPlan, PlanItem } from "../api/types";
import { tr } from "../i18n/tr";
import { shortDate } from "../lib/changes";
import { detailLines } from "./details";
import { kindColor } from "./kinds";

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
  const empty = day.items.length === 0 && !day.cancelled?.length && !day.tasks?.length;
  return (
    <section
      className={`@container min-w-0 rounded-2xl bg-white shadow-sm ring-1 dark:bg-slate-900 ${expanded ? "p-4" : "p-3"} ${
        isToday ? "ring-indigo-300 dark:ring-indigo-700" : "ring-slate-200 dark:ring-slate-800"
      }`}
    >
      <header className="mb-3 flex items-baseline justify-between gap-2">
        <h2 className={expanded ? "text-xl font-semibold" : "font-semibold"}>
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
          {timed.map((item) => (
            <Row key={`${item.type}-${String(item.id)}`} item={item} compact={!expanded} />
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

      {expanded && <Tasks title={tr.plan.tasks} tasks={day.tasks} />}
      {expanded && <Tasks title={tr.plan.weekTasks} tasks={day.week_tasks} />}
    </section>
  );
}

/**
 * One timed item. The title wraps to two lines and the end time sits under the start, so
 * nothing is cut; a tap opens everything (full title, time range, place, note).
 * In a narrow card (7-column week) the times go above the title.
 */
function Row({ item, compact }: { item: PlanItem; compact: boolean }) {
  const [open, setOpen] = useState(false);
  const color = kindColor(item.kind);
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
        className="min-w-0 flex-1 rounded-lg border-l-4 bg-slate-50 px-3 py-1.5 text-left hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-indigo-500 dark:bg-slate-800/60 dark:hover:bg-slate-800"
        style={{ borderColor: color }}
      >
        <span className={`block break-words font-medium leading-snug ${open ? "" : "line-clamp-2"}`}>{item.title}</span>
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

function Tasks({ title, tasks }: { title: string; tasks?: DayPlan["tasks"] }) {
  if (!tasks?.length) return null;
  return (
    <div className="mt-4">
      <h3 className="mb-1 text-sm font-medium text-slate-500 dark:text-slate-400">{title}</h3>
      <ul className="space-y-1 text-sm">
        {tasks.map((task) => (
          <li key={task.id} className={task.status === "done" ? "text-slate-400 line-through" : ""}>
            {task.status === "done" ? "☑" : "☐"} {task.title}
          </li>
        ))}
      </ul>
    </div>
  );
}
