import { useAttendance, useMonthUsage, useTeam, useTeamActivity, useTermWeeks } from "../api/queries";
import { AgentTag } from "../components/AgentTag";
import { YaverAvatar } from "../components/Yaver";
import { describeChange } from "../lib/changes";
import type { CourseAttendance } from "../api/types";
import { tr } from "../i18n/tr";
import { budgetTone, money } from "../lib/format";
import { Notice } from "../plan/DayView";
import { weekRange } from "../plan/week";
import { href } from "../lib/route";

export function StatusView() {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 px-3 py-4">
      <TermCard />
      <TeamCard />
      <AttendanceCard />
      <SpendCard />
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="yv-glass yv-rise rounded-3xl p-4">
      <h2 className="font-grotesk mb-3 text-lg font-semibold tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

function Bar({ ratio, tone }: { ratio: number; tone: "ok" | "warn" | "bad" }) {
  const color = { ok: "bg-emerald-500", warn: "bg-amber-500", bad: "bg-rose-500" }[tone];
  return (
    <div className="h-2 overflow-hidden rounded-full bg-slate-900/10 dark:bg-white/10">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${String(Math.min(ratio, 1) * 100)}%` }} />
    </div>
  );
}

/** Every week of the term: number, label, exams, absences; a tap opens that week. */
function TermCard() {
  const term = useTermWeeks();
  if (term.isPending) return <Notice text={tr.plan.loading} />;
  if (term.isError) return <Notice text={tr.plan.error} />;
  if (!term.data.term) {
    return (
      <Card title={tr.term.title}>
        <p className="text-sm text-slate-500 dark:text-slate-400">{tr.term.none}</p>
      </Card>
    );
  }
  const current = term.data.current_week_start;
  return (
    <Card title={`${tr.term.title} · ${term.data.term.name}`}>
      <ol className="-mx-2 max-h-[26rem] space-y-0.5 overflow-y-auto">
        {term.data.weeks.map((week) => {
          const isCurrent = week.week_start === current;
          const past = week.week_start < current;
          const counts = [
            week.exams ? tr.week.exams(week.exams) : null,
            week.absence_hours ? tr.week.absences(week.absence_hours) : null,
          ].filter(Boolean);
          return (
            <li key={week.week_start}>
              <a
                href={href("week", { week: week.week_start })}
                aria-current={isCurrent ? "date" : undefined}
                className={`flex items-baseline gap-3 rounded-xl px-2 py-1.5 text-sm hover:bg-white/60 dark:hover:bg-white/[0.06] ${
                  isCurrent ? "bg-indigo-500/10 ring-1 ring-indigo-400/40" : ""
                } ${past ? "text-slate-500 dark:text-slate-400" : ""}`}
              >
                <span className="w-7 shrink-0 text-right font-grotesk font-semibold tabular-nums">{tr.term.week(week.week_no)}</span>
                <span className="w-32 shrink-0 text-xs tabular-nums text-slate-500 dark:text-slate-400">{weekRange(week.week_start)}</span>
                <span className="min-w-0 flex-1 truncate">
                  {week.label && (
                    <span
                      className={`mr-2 rounded-full px-2 py-0.5 text-xs font-semibold ${
                        week.label_source === "user"
                          ? "bg-violet-500/15 text-violet-700 dark:text-violet-300"
                          : "bg-amber-500/15 text-amber-800 dark:text-amber-300"
                      }`}
                    >
                      {week.label}
                    </span>
                  )}
                  {isCurrent && <span className="text-xs font-medium text-indigo-600 dark:text-indigo-400">{tr.term.current}</span>}
                </span>
                <span
                  className={`shrink-0 text-xs tabular-nums ${week.absence_hours ? "text-rose-600 dark:text-rose-400" : "text-slate-500 dark:text-slate-400"}`}
                >
                  {counts.join(" · ")}
                </span>
              </a>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

/** Each yaver: colour label, area, last few things it changed. */
function TeamCard() {
  const team = useTeam();
  const activity = useTeamActivity();
  if (team.isPending) return <Notice text={tr.plan.loading} />;
  if (team.isError) return <Notice text={tr.plan.error} />;
  return (
    <Card title={tr.status.team}>
      <ul className="space-y-4">
        {[team.data.coordinator, ...team.data.agents].map((member) => {
          const recent = activity.data?.activity[member.id] ?? [];
          return (
            <li key={member.id}>
              <span className="flex items-center gap-2">
                <YaverAvatar member={member} size={28} />
                <AgentTag member={member} fallback={member.name} />
              </span>
              {member.domain && <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{member.domain}</p>}
              {recent.length > 0 ? (
                <ul className="mt-1 space-y-0.5 text-xs text-slate-500 dark:text-slate-400">
                  {recent.map((change, index) => (
                    <li key={`${change.at}-${String(index)}`} className={change.undone ? "line-through" : ""}>
                      {describeChange(change)}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-xs text-slate-400">{tr.status.noActivity}</p>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function AttendanceCard() {
  const attendance = useAttendance();
  if (attendance.isPending) return <Notice text={tr.plan.loading} />;
  if (attendance.isError) return <Notice text={tr.plan.error} />;
  const courses = attendance.data.courses;
  return (
    <Card title={tr.status.attendance}>
      {courses.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">{tr.status.noCourses}</p>
      ) : (
        <ul className="space-y-3">
          {courses.map((course) => (
            <CourseRow key={course.course} course={course} />
          ))}
        </ul>
      )}
    </Card>
  );
}

function CourseRow({ course }: { course: CourseAttendance }) {
  const limit = course.limit_hours;
  const remaining = course.remaining_hours ?? null;
  const ratio = limit ? course.absent_hours / limit : 0;
  const tone = remaining !== null && remaining <= 0 ? "bad" : ratio >= 0.75 ? "warn" : "ok";
  return (
    <li>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
        <span className="font-medium">
          {course.course}
          {course.name !== course.course && (
            <span className="font-normal text-slate-500 dark:text-slate-400"> · {course.name}</span>
          )}
        </span>
        <span className="shrink-0 text-slate-600 dark:text-slate-300">{tr.status.absences(course.absent_hours)}</span>
      </div>
      {course.baseline && course.baseline.hours > 0 && (
        <p className="mb-1 text-xs text-slate-500 dark:text-slate-400">
          {tr.status.baseline(course.baseline.hours, course.baseline.note)}
        </p>
      )}
      {limit ? (
        <>
          <Bar ratio={ratio} tone={tone} />
          <p className={`mt-1 text-xs ${tone === "bad" ? "text-rose-600 dark:text-rose-400" : "text-slate-500 dark:text-slate-400"}`}>
            {remaining !== null && remaining < 0 ? tr.status.over(limit) : tr.status.remaining(Math.max(remaining ?? 0, 0))}
          </p>
        </>
      ) : (
        <p className="text-xs text-slate-500 dark:text-slate-400">{tr.status.noLimit}</p>
      )}
    </li>
  );
}

function SpendCard() {
  const usage = useMonthUsage();
  if (usage.isPending) return <Notice text={tr.plan.loading} />;
  if (usage.isError) return <Notice text={tr.plan.error} />;
  const { budget, by_model: byModel } = usage.data;
  return (
    <Card title={`${tr.status.spend} · ${usage.data.month}`}>
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span>{tr.status.claude}</span>
        <span className="tabular-nums">{tr.status.budget(money(budget.spent_usd), money(budget.limit_usd))}</span>
      </div>
      <Bar ratio={budget.ratio ?? 1} tone={budgetTone(budget.level)} />
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{tr.status.levels[budget.level]}</p>
      {byModel.length > 0 && (
        <>
          <h3 className="mb-1 mt-4 text-sm font-medium text-slate-500 dark:text-slate-400">{tr.status.byModel}</h3>
          <ul className="space-y-1 text-sm">
            {byModel.map((row) => (
              <li key={`${row.provider}/${row.model}/${row.tier}`} className="flex justify-between gap-2">
                <span className="truncate">
                  {row.model} <span className="text-xs text-slate-500">· {tr.status.calls(row.calls)}</span>
                </span>
                <span className="shrink-0 tabular-nums">${money(row.cost_usd, 4)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
