import type { Team } from "../api/types";
import { greeting, todayLabel, useNowMinutes } from "../design/time";
import { tr } from "../i18n/tr";

/** "İyi akşamlar, Görkem" over the date and the team, at the top of the chat. */
export function Greeting({ team, large = false }: { team: Team | undefined; large?: boolean }) {
  const minutes = useNowMinutes();
  const name = team?.user_name ?? "";
  return (
    <header className={`yv-rise ${large ? "text-center" : ""}`}>
      <p className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
        {todayLabel()}
      </p>
      <h1
        className={`font-grotesk mt-1 font-semibold leading-[1.05] tracking-tight ${large ? "text-4xl" : "text-[1.9rem]"}`}
      >
        {greeting(minutes)}
        {name ? (
          <>
            , <span className="yv-name-gradient">{name}</span>
          </>
        ) : null}
      </h1>
      {team && (
        <ul className={`mt-3 flex flex-wrap gap-1.5 ${large ? "justify-center" : ""}`} aria-label={tr.status.team}>
          {team.agents.map((agent) => (
            <li
              key={agent.id}
              className="yv-glass inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs"
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: agent.color }} aria-hidden />
              <span className="font-medium">{agent.name}</span>
              <span className="text-slate-500 dark:text-slate-400">{agent.domain.split(",")[0]}</span>
            </li>
          ))}
        </ul>
      )}
    </header>
  );
}
