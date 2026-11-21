import { execFileSync } from "node:child_process";

/** The e2e database container (project yaver-e2e). Never the main stack's yaver-db-1. */
const CONTAINER = process.env.E2E_DB_CONTAINER ?? "yaver-e2e-db-1";
if (!CONTAINER.startsWith("yaver-e2e-")) throw new Error(`refusing to touch ${CONTAINER}`);

/** Runs SQL in the e2e database; returns rows as arrays of strings (psql -At, "|" separated). */
export function sql(query: string): string[][] {
  const out = execFileSync(
    "docker",
    ["exec", "-i", CONTAINER, "psql", "-U", "yaver_e2e", "-d", "yaver_e2e", "-v", "ON_ERROR_STOP=1", "-At", "-q"],
    { input: query, encoding: "utf8" },
  );
  return out
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => line.split("|"));
}

export function scalar(query: string): string | undefined {
  return sql(query)[0]?.[0];
}

/** '...' literal for SQL built in tests (fixed test strings only). */
export const lit = (value: string): string => `'${value.replace(/'/g, "''")}'`;

/** Total LLM spend recorded in the e2e database (USD). */
export function spentUsd(): number {
  return Number(scalar("SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage;") ?? "0");
}
