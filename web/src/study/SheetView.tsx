import { useQuery } from "@tanstack/react-query";

import { apiGet } from "../api/client";
import type { StudySheet } from "../api/types";
import { Markdown } from "../components/Markdown";
import { tr } from "../i18n/tr";
import { href, useHashParam } from "../lib/route";
import { Notice } from "../plan/DayView";

/** One study sheet (#/sheet?id=3): Markdown with its sources; download as .md or print
 * to PDF (the browser's "Save as PDF" keeps Turkish characters and needs no server work). */
export function SheetView() {
  const [id] = useHashParam("id");
  const sheet = useQuery({
    queryKey: ["plan", "study-sheet", id],
    queryFn: ({ signal }) => apiGet<StudySheet>(`/study-sheets/${String(id)}`, { signal }),
    enabled: id !== null && /^\d+$/.test(id),
  });
  if (id === null || !/^\d+$/.test(id)) return <Notice text={tr.study.notFound} />;
  if (sheet.isPending) return <Notice text={tr.plan.loading} />;
  if (sheet.isError) return <Notice text={tr.study.notFound} />;
  const data = sheet.data;
  const meta = [data.course, data.week ? tr.study.week(data.week) : null, tr.study.date(data.created_at)]
    .filter(Boolean)
    .join(" · ");
  return (
    <article className="mx-auto max-w-3xl px-3 py-4 print:max-w-none print:p-0">
      <div className="mb-3 flex items-center gap-1.5 print:hidden sm:gap-2">
        <a
          href={href("status")}
          className="shrink-0 rounded-full px-2 py-1.5 text-sm text-slate-600 hover:bg-white/60 dark:text-slate-300 dark:hover:bg-white/10"
        >
          ‹ {tr.study.back}
        </a>
        <span className="min-w-0 flex-1" />
        <a
          href={`/api/study-sheets/${String(data.id)}/download.md`}
          className="rounded-full bg-indigo-500/10 px-3 py-2 text-sm sm:px-4 font-semibold text-indigo-700 hover:bg-indigo-500/20 dark:text-indigo-300"
        >
          {tr.study.downloadMd}
        </a>
        <button
          type="button"
          onClick={() => {
            window.print();
          }}
          className="rounded-full bg-gradient-to-r from-indigo-500 to-fuchsia-500 px-3 py-2 text-sm sm:px-4 font-semibold text-white"
        >
          {tr.study.pdf}
        </button>
      </div>
      <div className="yv-glass yv-rise rounded-3xl p-5 sm:p-7 print:rounded-none print:p-0">
        <header className="mb-4 border-b border-slate-900/10 pb-3 dark:border-white/10">
          <h1 className="font-grotesk text-2xl font-semibold tracking-tight sm:text-3xl">{data.title}</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{meta}</p>
        </header>
        <div className="study-sheet">
          <Markdown text={data.content_md} />
        </div>
        <p className="mt-6 text-xs text-slate-400 print:hidden">{tr.study.note}</p>
      </div>
    </article>
  );
}
