import { useQuery } from "@tanstack/react-query";

import { apiGet } from "../api/client";
import type { StudySheetSummary } from "../api/types";
import { tr } from "../i18n/tr";
import { href } from "../lib/route";
import { Card } from "../status/Card";

/** Study sheets written so far (status page); a tap opens one. */
export function SheetsCard() {
  const sheets = useQuery({
    queryKey: ["plan", "study-sheets"], // under "plan": a new sheet shows after the answer
    queryFn: ({ signal }) => apiGet<{ sheets: StudySheetSummary[] }>("/study-sheets", { signal }),
  });
  if (!sheets.data) return null;
  return (
    <Card title={tr.study.title}>
      {sheets.data.sheets.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">{tr.study.empty}</p>
      ) : (
        <ul className="-mx-2 space-y-0.5">
          {sheets.data.sheets.map((sheet) => (
            <li key={sheet.id}>
              <a
                href={href("sheet", { id: String(sheet.id) })}
                className="flex items-baseline gap-3 rounded-xl px-2 py-1.5 hover:bg-white/60 dark:hover:bg-white/[0.06]"
              >
                <span className="min-w-0 flex-1 truncate font-medium">{sheet.title}</span>
                <span className="shrink-0 text-xs text-slate-500 dark:text-slate-400">
                  {tr.study.sources(sheet.sources)} · {tr.study.date(sheet.created_at)}
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
