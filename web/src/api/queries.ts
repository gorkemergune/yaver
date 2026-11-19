import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";
import type {
  Change,
  CourseAttendance,
  DayPlanResponse,
  MonthUsage,
  Team,
  WeekPlanResponse,
} from "./types";

/** Query keys of data the chat can change: refreshed after every answer / undo. */
export const MUTABLE_KEYS = [["plan"], ["attendance"], ["usage"]] as const;

export function useTeam() {
  return useQuery({
    queryKey: ["team"],
    queryFn: ({ signal }) => apiGet<Team>("/team", { signal }),
    staleTime: Infinity,
  });
}

export function useTeamActivity() {
  return useQuery({
    queryKey: ["plan", "team-activity"], // under "plan": refreshed after chat answers / undo
    queryFn: ({ signal }) =>
      apiGet<{ activity: Record<string, (Change & { at: string })[]> }>("/team/activity", { signal }),
  });
}

export function useDayPlan(offset: 0 | 1) {
  return useQuery({
    queryKey: ["plan", "day", offset],
    queryFn: async ({ signal }) => {
      if (offset === 0) return apiGet<DayPlanResponse>("/plan/day", { signal });
      const today = await apiGet<DayPlanResponse>("/plan/day", { signal });
      const next = new Date(`${today.today}T12:00:00`);
      next.setDate(next.getDate() + 1);
      return apiGet<DayPlanResponse>(`/plan/day?date=${isoDate(next)}`, { signal });
    },
  });
}

export function useWeekPlan() {
  return useQuery({
    queryKey: ["plan", "week"],
    queryFn: ({ signal }) => apiGet<WeekPlanResponse>("/plan/week", { signal }),
  });
}

export function useAttendance() {
  return useQuery({
    queryKey: ["attendance"],
    queryFn: ({ signal }) => apiGet<{ courses: CourseAttendance[] }>("/attendance", { signal }),
  });
}

export function useMonthUsage() {
  return useQuery({
    queryKey: ["usage", "month"],
    queryFn: ({ signal }) => apiGet<MonthUsage>("/usage/month", { signal }),
    refetchInterval: 60_000,
  });
}

export function isoDate(date: Date): string {
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
