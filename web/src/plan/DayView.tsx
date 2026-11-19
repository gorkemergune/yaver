import { useDayPlan } from "../api/queries";
import type { DayPlan, PlanItem } from "../api/types";
import { tr } from "../i18n/tr";
import { shortDate } from "../lib/changes";
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
      className={`rounded-2xl bg-white p-4 shadow-sm ring-1 dark:bg-slate-900 ${
        isToday ? "ring-indigo-300 dark:ring-indigo-700" : "ring-slate-200 dark:ring-slate-800"
      }`}
    >
      <header className="mb-3 flex items-baseline justify-between">
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
        <div className="mb-2 flex flex-wrap gap-1.5">
          {allDay.map((item) => (
            <span
              key={`${item.type}-${String(item.id)}`}
              className="rounded-full px-2.5 py-1 text-xs font-medium"
              style={{ color: kindColor(item.kind), backgroundColor: `${kindColor(item.kind)}1f` }}
            >
              {item.title}
            </span>
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
            <li key={`c-${String(cancelled.block_id)}`} className="flex gap-3 text-sm text-slate-400 line-through">
              <span className="w-12 shrink-0 tabular-nums">{cancelled.start}</span>
              <span>
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

function Row({ item, compact }: { item: PlanItem; compact: boolean }) {
  const color = kindColor(item.kind);
  return (
    <li className="flex gap-3">
      <span className="w-12 shrink-0 pt-1.5 text-sm tabular-nums text-slate-500 dark:text-slate-400">
        {item.start ?? ""}
      </span>
      <div
        className="min-w-0 flex-1 rounded-lg border-l-4 bg-slate-50 px-3 py-1.5 dark:bg-slate-800/60"
        style={{ borderColor: color }}
      >
        <div className="flex items-baseline justify-between gap-2">
          <span className="truncate font-medium">{item.title}</span>
          {item.end && <span className="shrink-0 text-xs tabular-nums text-slate-500">→ {item.end}</span>}
        </div>
        {!compact && (
          <div className="text-xs text-slate-500 dark:text-slate-400">
            {tr.kinds[item.kind] ?? item.kind}
            {item.location ? ` · ${item.location}` : ""}
            {item.moved_from ? ` · ${tr.plan.moved(item.moved_from.slice(11))}` : ""}
            {item.starts_on ? ` · ${shortDate(item.starts_on)}` : ""}
          </div>
        )}
      </div>
    </li>
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
