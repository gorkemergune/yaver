import { useWeekPlan } from "../api/queries";
import { tr } from "../i18n/tr";
import { DayCard, Notice } from "./DayView";

/** Monday-Sunday: stacked on a phone, a grid on wide screens. */
export function WeekView() {
  const week = useWeekPlan();
  if (week.isPending) return <Notice text={tr.plan.loading} />;
  if (week.isError) return <Notice text={tr.plan.error} />;
  return (
    <div className="mx-auto grid max-w-6xl gap-3 px-3 py-4 md:grid-cols-2 xl:grid-cols-4">
      {week.data.days.map((day) => (
        <DayCard key={day.date} day={day} today={week.data.today} />
      ))}
    </div>
  );
}
