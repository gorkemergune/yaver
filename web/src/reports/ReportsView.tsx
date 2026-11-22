import { useQuery } from "@tanstack/react-query";

import { apiGet } from "../api/client";
import { isoDate, useTeam } from "../api/queries";
import type { Member } from "../api/types";
import { tr } from "../i18n/tr";
import { useHashParam } from "../lib/route";
import { Card } from "../status/Card";
import { shiftDate, type OfficeReport } from "./model";

function useReport(period: "day" | "week", date: string | null) {
  return useQuery({
    queryKey: ["usage", "reports", period, date ?? "today"], // under "usage": refreshed after answers
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ period, ...(date ? { date } : {}) });
      return apiGet<OfficeReport>(`/reports?${params.toString()}`, { signal });
    },
    refetchInterval: 60_000,
  });
}

const time = (iso: string): string =>
  new Date(iso).toLocaleString("tr-TR", {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

/** Raporlar: a day or a week of the office, read only (GET /api/reports). */
export function ReportsView() {
  const [periodParam, setPeriod] = useHashParam("period");
  const [date, setDate] = useHashParam("date");
  const period = periodParam === "week" ? "week" : "day";
  const report = useReport(period, date);
  const team = useTeam().data;
  const members: Record<string, Member> = Object.fromEntries(
    team ? [team.coordinator, ...team.agents].map((m) => [m.id, m]) : [],
  );
  const name = (id: string | null): string =>
    id ? (members[id]?.name ?? id) : tr.appName;
  const data = report.data;
  const base = date ?? isoDate(new Date());
  const step = period === "week" ? 7 : 1;

  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-4 px-3 py-4 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="font-grotesk mr-auto text-2xl font-semibold tracking-tight">
          {tr.reports.title}
        </h1>
        {(["day", "week"] as const).map((p) => (
          <button
            key={p}
            type="button"
            aria-pressed={period === p}
            onClick={() => {
              setPeriod(p === "day" ? null : p);
            }}
            className={`min-h-9 rounded-full px-3 text-sm font-medium ${period === p ? "bg-indigo-600 text-white" : "yv-glass"}`}
          >
            {tr.reports.period[p]}
          </button>
        ))}
        <span className="flex items-center gap-1">
          <button
            type="button"
            className="yv-glass min-h-9 rounded-full px-3 text-sm"
            aria-label={tr.reports.prev}
            onClick={() => {
              setDate(shiftDate(base, -step));
            }}
          >
            ‹
          </button>
          <span className="min-w-32 text-center text-sm tabular-nums">
            {data
              ? data.from === data.to
                ? data.from
                : `${data.from} – ${data.to}`
              : "…"}
          </span>
          <button
            type="button"
            className="yv-glass min-h-9 rounded-full px-3 text-sm"
            aria-label={tr.reports.next}
            onClick={() => {
              setDate(shiftDate(base, step));
            }}
          >
            ›
          </button>
        </span>
        {date && (
          <button
            type="button"
            className="min-h-9 rounded-full px-3 text-sm text-indigo-600 dark:text-[#b3a6ff]"
            onClick={() => {
              setDate(null);
            }}
          >
            {tr.reports.today}
          </button>
        )}
      </div>

      {report.isError && (
        <p role="alert" className="text-sm text-rose-600">
          {tr.reports.failed}
        </p>
      )}
      {data && (
        <>
          <Card title={tr.reports.employees}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead className="text-left text-xs text-slate-500 dark:text-slate-400">
                  <tr>
                    {tr.reports.columns.map((c) => (
                      <th key={c} className="py-1 pr-3 font-medium">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {data.employees.map((e) => (
                    <tr
                      key={e.id}
                      className="border-t border-slate-900/5 dark:border-white/10"
                    >
                      <td
                        className="py-1.5 pr-3 font-medium"
                        style={{ color: members[e.id]?.color ?? undefined }}
                      >
                        {e.name}
                      </td>
                      <td className="pr-3">{e.requests}</td>
                      <td className="pr-3">{e.delegated}</td>
                      <td className="pr-3">{e.shift}</td>
                      <td
                        className={`pr-3 ${e.failed ? "text-rose-600 dark:text-rose-400" : ""}`}
                      >
                        {e.failed}
                      </td>
                      <td
                        className={`pr-3 ${e.handoffs ? "text-amber-700 dark:text-amber-300" : ""}`}
                      >
                        {e.handoffs}
                      </td>
                      <td className="pr-3">{e.tool_errors}</td>
                      <td className="pr-3">${e.cost_usd}</td>
                    </tr>
                  ))}
                  <tr className="border-t-2 border-slate-900/10 font-semibold dark:border-white/20">
                    <td className="py-1.5 pr-3">{tr.reports.total}</td>
                    <td className="pr-3">{data.totals.requests}</td>
                    <td className="pr-3">{data.totals.delegated}</td>
                    <td className="pr-3">{data.totals.shift}</td>
                    <td className="pr-3">{data.totals.failed}</td>
                    <td className="pr-3">{data.totals.handoffs}</td>
                    <td className="pr-3">{data.totals.tool_errors}</td>
                    <td className="pr-3">${data.totals.cost_usd}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>

          <Card title={tr.reports.problems(data.problems.length)}>
            {data.problems.length === 0 ? (
              <p className="text-sm text-slate-500">{tr.reports.noProblems}</p>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {data.problems.map((p, i) => (
                  <li
                    key={`${p.at}-${String(i)}`}
                    className="rounded-2xl bg-slate-900/[0.03] px-3 py-2 dark:bg-white/5"
                  >
                    <span
                      className={`mr-2 rounded-full px-2 py-0.5 text-xs font-medium ${p.kind === "failed" ? "bg-rose-500/15 text-rose-700 dark:text-rose-300" : "bg-amber-500/15 text-amber-800 dark:text-amber-200"}`}
                    >
                      {p.kind === "failed"
                        ? tr.reports.failedTag
                        : tr.reports.handoffTag}
                    </span>
                    <span className="font-medium">{name(p.agent_id)}</span>
                    <span className="ml-2 text-xs text-slate-500">
                      {time(p.at)}
                    </span>
                    <p className="mt-1">“{p.text}”</p>
                    <p className="text-xs text-slate-600 dark:text-slate-300">
                      {tr.reports.reason}: {p.reason || "—"}
                      {p.kind === "handoff" &&
                        ` · ${tr.reports.area}: ${p.area === undefined || p.area === "" ? tr.reports.noArea : p.area}${p.in_words ? ` · ${tr.reports.inWords}` : ""}`}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title={tr.reports.routing(data.routing.length)}>
            {data.routing.length === 0 ? (
              <p className="text-sm text-slate-500">{tr.reports.noRouting}</p>
            ) : (
              <ul className="flex flex-col divide-y divide-slate-900/5 text-sm dark:divide-white/10">
                {data.routing.map((r) => (
                  <li
                    key={r.message_id}
                    className="flex flex-wrap items-baseline gap-x-2 py-1.5"
                  >
                    <span className="text-xs text-slate-500">{time(r.at)}</span>
                    <span className="min-w-0 flex-1 truncate" title={r.text}>
                      “{r.text}”
                    </span>
                    <span className="text-xs text-slate-600 dark:text-slate-300">
                      {r.intents.length
                        ? r.intents
                            .map(
                              ([intent, owner]) => `${intent} → ${name(owner)}`,
                            )
                            .join(", ")
                        : tr.reports.unclassified}
                    </span>
                    {r.handoffs > 0 && (
                      <span className="text-xs text-amber-700 dark:text-amber-300">
                        ↩ {r.handoffs}
                      </span>
                    )}
                    {r.errors > 0 && (
                      <span className="text-xs text-rose-600">
                        ⚠ {r.errors}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title={tr.reports.bugs(data.bugs.open)}>
            {data.bugs.latest.length === 0 ? (
              <p className="text-sm text-slate-500">{tr.reports.noBugs}</p>
            ) : (
              <ul className="flex flex-col gap-1.5 text-sm">
                {data.bugs.latest.map((b) => (
                  <li key={b.id}>
                    <span className="font-medium">#{b.id}</span>
                    <span className="ml-2 text-xs text-slate-500">
                      {time(b.at)} · {name(b.agent_id)} · {b.source}
                    </span>
                    <p>
                      {b.note || "—"}{" "}
                      <span className="text-xs text-slate-500">
                        (“{b.text}”)
                      </span>
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2 text-xs text-slate-500">
              {tr.reports.exportHint}
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
