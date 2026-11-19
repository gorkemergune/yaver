import { useWeekPlan } from "../api/queries";
import { tr } from "../i18n/tr";
import { DayCard, Notice } from "./DayView";

/** Monday-Sunday: stacked on a phone, two columns on a tablet, the whole week as seven
 * columns on a wide screen (cards switch to their narrow layout by container width). */
export function WeekView() {
  const week = useWeekPlan();
  if (week.isPending) return <Notice text={tr.plan.loading} />;
  if (week.isError) return <Notice text={tr.plan.error} />;
  return (
    <div className="mx-auto grid max-w-6xl items-start gap-3 px-3 py-4 md:grid-cols-2 xl:max-w-[1800px] xl:grid-cols-7 xl:gap-2">
      {week.data.days.map((day) => (
        <DayCard key={day.date} day={day} today={week.data.today} />
      ))}
    </div>
  );
}
