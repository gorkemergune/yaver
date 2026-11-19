import type { MonthUsage } from "../api/types";

export function budgetTone(level: MonthUsage["budget"]["level"]): "ok" | "warn" | "bad" {
  return level === "limit" ? "bad" : level === "downgrade" ? "warn" : "ok";
}

/** "0.1234" -> "0.12" (API sends decimals as strings). */
export function money(value: string, digits = 2): string {
  return Number(value).toFixed(digits);
}
