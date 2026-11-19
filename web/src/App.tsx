import type { ReactNode } from "react";

import { useMonthUsage } from "./api/queries";
import { ChatView } from "./chat/ChatView";
import { ConnectionStatus } from "./components/ConnectionStatus";
import {
  ArrowRightIcon,
  CalendarIcon,
  ChatIcon,
  GaugeIcon,
  MonitorIcon,
  MoonIcon,
  SunriseIcon,
} from "./components/icons";
import { tr } from "./i18n/tr";
import { href, useRoute, type Route } from "./lib/route";
import { useTheme } from "./lib/theme";
import { DayView } from "./plan/DayView";
import { WeekView } from "./plan/WeekView";
import { budgetTone, money } from "./lib/format";
import { StatusView } from "./status/StatusView";

const NAV: { route: Route; label: string; icon: ReactNode }[] = [
  { route: "chat", label: tr.nav.chat, icon: <ChatIcon /> },
  { route: "today", label: tr.nav.today, icon: <SunriseIcon /> },
  { route: "tomorrow", label: tr.nav.tomorrow, icon: <ArrowRightIcon /> },
  { route: "week", label: tr.nav.week, icon: <CalendarIcon /> },
  { route: "status", label: tr.nav.status, icon: <GaugeIcon /> },
];

export function App() {
  const route = useRoute();
  return (
    <div className="flex h-dvh flex-col">
      <Header route={route} />
      <main className="min-h-0 flex-1 overflow-y-auto">
        {route === "chat" && <ChatView />}
        {route === "today" && <DayView offset={0} />}
        {route === "tomorrow" && <DayView offset={1} />}
        {route === "week" && <WeekView />}
        {route === "status" && <StatusView />}
      </main>
      <BottomNav route={route} />
    </div>
  );
}

function Header({ route }: { route: Route }) {
  const { theme, cycle } = useTheme();
  const themeIcon = { system: <MonitorIcon />, light: <SunriseIcon />, dark: <MoonIcon /> }[theme];
  return (
    <header className="border-b border-slate-200 bg-white/90 pt-[env(safe-area-inset-top)] backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-3 px-3">
        <a href={href("chat")} className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <span className="text-lg font-semibold">{tr.appName}</span>
        </a>
        <nav className="ml-4 hidden gap-1 md:flex">
          {NAV.map((item) => (
            <NavLink key={item.route} item={item} active={route === item.route} inline />
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden sm:inline">
            <ConnectionStatus />
          </span>
          <SpendPill />
          <button
            type="button"
            onClick={cycle}
            title={tr.theme[theme]}
            aria-label={tr.theme[theme]}
            className="flex h-10 w-10 items-center justify-center rounded-full text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            {themeIcon}
          </button>
        </div>
      </div>
    </header>
  );
}

/** "Claude $0.12 / $4" — colour by budget level; opens the status page. */
function SpendPill() {
  const usage = useMonthUsage();
  if (!usage.data) return null;
  const { budget } = usage.data;
  const tone = {
    ok: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    warn: "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300",
    bad: "bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300",
  }[budgetTone(budget.level)];
  return (
    <a
      href={href("status")}
      title={tr.status.levels[budget.level]}
      className={`rounded-full px-2.5 py-1 text-xs font-medium tabular-nums ${tone}`}
    >
      {tr.status.claude} ${money(budget.spent_usd)} / ${money(budget.limit_usd, 0)}
    </a>
  );
}

function BottomNav({ route }: { route: Route }) {
  return (
    <nav className="border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden dark:border-slate-800 dark:bg-slate-950/95">
      <ul className="grid grid-cols-5">
        {NAV.map((item) => (
          <li key={item.route}>
            <NavLink item={item} active={route === item.route} />
          </li>
        ))}
      </ul>
    </nav>
  );
}

function NavLink({
  item,
  active,
  inline = false,
}: {
  item: (typeof NAV)[number];
  active: boolean;
  inline?: boolean;
}) {
  const color = active
    ? "text-indigo-600 dark:text-indigo-400"
    : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200";
  if (inline) {
    return (
      <a
        href={href(item.route)}
        aria-current={active ? "page" : undefined}
        className={`rounded-lg px-3 py-1.5 text-sm font-medium ${color} ${active ? "bg-indigo-50 dark:bg-indigo-950/50" : ""}`}
      >
        {item.label}
      </a>
    );
  }
  return (
    <a
      href={href(item.route)}
      aria-current={active ? "page" : undefined}
      className={`flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-medium ${color}`}
    >
      {item.icon}
      {item.label}
    </a>
  );
}
