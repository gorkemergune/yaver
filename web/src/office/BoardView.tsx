import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { apiGet } from "../api/client";
import type { BoardCard, BoardColumn, BoardResponse } from "../api/types";
import { tr } from "../i18n/tr";
import { href } from "../lib/route";
import { useOffice } from "./useOffice";

const COLUMNS: BoardColumn[] = ["waiting", "running", "approval", "done"];
const ACCENT: Record<BoardColumn, string> = {
  waiting: "bg-slate-400",
  running: "bg-amber-400",
  approval: "bg-[#ff6b6b]",
  done: "bg-emerald-400",
};

const hm = (iso: string): string => new Date(iso).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
const when = (iso: string): string =>
  new Date(iso).toLocaleString("tr-TR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** Görev panosu: the employees' inboxes as kanban columns (GET /api/office/board), live:
 *  refreshed whenever the office stream reports a change. */
export function BoardView() {
  const office = useOffice();
  const board = useQuery({
    queryKey: ["office", "board"],
    queryFn: ({ signal }) => apiGet<BoardResponse>("/office/board", { signal }),
    refetchInterval: 30_000,
  });
  const { refetch } = board;
  const latest = office.feed[0]?.id;
  useEffect(() => {
    if (latest) void refetch();
  }, [latest, refetch]);

  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-4 px-3 py-4 sm:px-6">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="font-grotesk text-[26px] font-bold">{tr.board.title}</h1>
        <span className="text-[13px] text-slate-500 dark:text-[#9aa2c9]">{tr.board.hint}</span>
      </div>
      {!board.data ? (
        <p className="text-sm text-slate-500">{tr.board.loading}</p>
      ) : (
        <div className="-mx-3 flex snap-x snap-mandatory gap-3 overflow-x-auto px-3 pb-2 md:mx-0 md:grid md:grid-cols-4 md:overflow-visible md:px-0">
          {COLUMNS.map((column) => {
            const cards = board.data.cards.filter((c) => c.column === column);
            return (
              <section
                key={column}
                aria-label={tr.board.columns[column]}
                className="yv-glass flex w-[78vw] max-w-[340px] flex-none snap-start flex-col gap-2.5 rounded-[20px] p-3.5 md:w-auto md:max-w-none"
              >
                <h2 className="flex items-center gap-2 px-1 text-sm font-semibold">
                  <span className={`h-2 w-2 rounded-full ${ACCENT[column]}`} />
                  {tr.board.columns[column]}
                  <span className="ml-auto text-xs font-normal text-slate-500 dark:text-[#9aa2c9]">{cards.length}</span>
                </h2>
                {cards.length === 0 ? (
                  <p className="px-1 pb-1 text-[13px] text-slate-400 dark:text-[#6f76a0]">{tr.board.empty}</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {cards.map((card) => (
                      <Card key={card.id} card={card} name={office.staff[card.employee_id]?.name} color={office.staff[card.employee_id]?.color} />
                    ))}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Card({ card, name, color }: { card: BoardCard; name: string | undefined; color: string | undefined }) {
  const accent = color ?? "#9d8cff";
  return (
    <li>
      <a
        href={href("office", { employee: card.employee_id })}
        className="yv-inset block rounded-xl border-l-[3px] px-3 py-2.5 text-[13px] leading-snug transition-colors hover:bg-white/80 dark:hover:bg-white/10"
        style={{ borderLeftColor: accent }}
      >
        <span className="flex items-center gap-2 text-xs">
          <span className="font-bold" style={{ color: accent }}>
            {name ?? card.employee_id}
          </span>
          <span className="text-slate-500 dark:text-[#9aa2c9]">{tr.board.sources[card.source]}</span>
          <span className="ml-auto tabular-nums text-slate-500 dark:text-[#9aa2c9]">
            {card.status === "scheduled" ? tr.board.scheduled(hm(card.at)) : when(card.at)}
          </span>
        </span>
        <span className="mt-1 line-clamp-3 block">{card.title}</span>
        {card.status === "failed" && <span className="mt-1 block text-xs text-rose-500">{tr.board.failed}</span>}
        {card.result && card.column !== "waiting" && (
          <span className="mt-1 line-clamp-2 block text-xs text-slate-500 dark:text-[#9aa2c9]">{card.result}</span>
        )}
      </a>
    </li>
  );
}
