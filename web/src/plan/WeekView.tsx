import { useEffect, useRef } from "react";

import { useWeekPlan } from "../api/queries";
import type { WeekFacts } from "../api/types";
import { tr } from "../i18n/tr";
import { useHashParam } from "../lib/route";
import { DayCard, Notice, Tasks } from "./DayView";
import { mondayOf, shiftWeek, swipeDirection, weekParam, weekRange } from "./week";

/**
 * Any week, Monday-Sunday: stacked on a phone, two columns on a tablet, seven columns on a
 * wide screen. ‹ › buttons, ←/→ keys and a swipe page through weeks; the week is kept in
 * the URL (#/week?week=2026-11-16) so a reload stays on it.
 */
export function WeekView() {
  const [param, setParam] = useHashParam("week");
  const wanted = weekParam(param);
  const week = useWeekPlan(wanted);
  const data = week.data;
  const thisWeek = data ? mondayOf(data.today) : null;
  const shown = data?.week_start ?? wanted;

  const go = (weeks: number): void => {
    if (!shown) return;
    const target = shiftWeek(shown, weeks);
    setParam(target === thisWeek ? null : target);
  };
  const goRef = useRef(go);
  useEffect(() => {
    goRef.current = go;
  });

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      const typing =
        event.target instanceof Element && event.target.closest("input, textarea, select, [contenteditable]");
      if (typing || event.altKey || event.metaKey || event.ctrlKey) return;
      if (event.key === "ArrowLeft") goRef.current(-1);
      if (event.key === "ArrowRight") goRef.current(1);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const touch = useRef<{ x: number; y: number } | null>(null);

  if (week.isPending) return <Notice text={tr.plan.loading} />;
  if (week.isError || !data) return <Notice text={tr.plan.error} />;
  const isThisWeek = data.week_start === thisWeek;
  const weekTasks = data.days[0]?.week_tasks;
  return (
    <div
      className="mx-auto max-w-6xl px-3 py-4 xl:max-w-[1800px]"
      onTouchStart={(event) => {
        const t = event.touches[0];
        touch.current = t ? { x: t.clientX, y: t.clientY } : null;
      }}
      onTouchEnd={(event) => {
        const start = touch.current;
        const t = event.changedTouches[0];
        touch.current = null;
        if (!start || !t) return;
        const direction = swipeDirection(t.clientX - start.x, t.clientY - start.y);
        if (direction !== 0) go(direction);
      }}
    >
      <WeekHeader
        facts={data.week}
        isThisWeek={isThisWeek}
        loading={week.isPlaceholderData}
        onPrevious={() => {
          go(-1);
        }}
        onNext={() => {
          go(1);
        }}
        onThisWeek={() => {
          setParam(null);
        }}
      />
      {weekTasks?.length ? (
        <div className="yv-glass mb-3 rounded-3xl px-4 py-1">
          <Tasks title={tr.plan.weekTasks} tasks={weekTasks} />
        </div>
      ) : null}
      <div
        key={data.week_start}
        className={`grid items-start gap-3 transition-opacity md:grid-cols-2 xl:grid-cols-7 xl:gap-2 ${week.isPlaceholderData ? "opacity-60" : ""}`}
      >
        {data.days.map((day) => (
          <DayCard key={day.date} day={day} today={data.today} />
        ))}
      </div>
    </div>
  );
}

function WeekHeader({
  facts,
  isThisWeek,
  loading,
  onPrevious,
  onNext,
  onThisWeek,
}: {
  facts: WeekFacts;
  isThisWeek: boolean;
  loading: boolean;
  onPrevious: () => void;
  onNext: () => void;
  onThisWeek: () => void;
}) {
  const arrow =
    "flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-2xl leading-none text-slate-600 hover:bg-white/70 focus-visible:outline-2 focus-visible:outline-indigo-500 dark:text-slate-300 dark:hover:bg-white/10";
  const counts = [
    facts.exams ? tr.week.exams(facts.exams) : null,
    facts.quizzes ? tr.week.quizzes(facts.quizzes) : null,
    facts.absence_hours ? tr.week.absences(facts.absence_hours) : null,
    facts.holidays.length ? tr.week.holiday(facts.holidays.join(", ")) : null,
  ].filter(Boolean);
  return (
    <header className="yv-glass mb-3 flex items-center gap-1 rounded-3xl px-2 py-2 sm:gap-2 sm:px-3" aria-busy={loading}>
      <button type="button" onClick={onPrevious} aria-label={tr.week.previous} title={tr.week.previous} className={arrow}>
        ‹
      </button>
      <div className="min-w-0 flex-1 text-center">
        <h2 className="font-grotesk text-base font-semibold leading-tight tracking-tight text-balance sm:text-xl">
          {facts.title ?? tr.week.outside}
        </h2>
        <p
          className="mt-1 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs text-slate-500 sm:text-sm dark:text-slate-400"
          title={tr.week.hint}
        >
          {facts.label && (
            <span
              title={facts.label_source === "user" ? tr.week.userLabel : tr.week.autoLabel}
              className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                facts.label_source === "user"
                  ? "bg-violet-500/15 text-violet-700 dark:text-violet-300"
                  : "bg-amber-500/15 text-amber-800 dark:text-amber-300"
              }`}
            >
              {facts.label}
            </span>
          )}
          <span>{weekRange(facts.week_start)}</span>
          {counts.length > 0 && <span className="text-slate-400 dark:text-slate-500">{counts.join(" · ")}</span>}
        </p>
      </div>
      {!isThisWeek && (
        <button
          type="button"
          onClick={onThisWeek}
          className="shrink-0 rounded-full bg-indigo-500/10 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-500/20 dark:text-indigo-300"
        >
          {tr.week.thisWeek}
        </button>
      )}
      <button type="button" onClick={onNext} aria-label={tr.week.next} title={tr.week.next} className={arrow}>
        ›
      </button>
    </header>
  );
}
