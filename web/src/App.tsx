import { lazy, Suspense, type ReactNode } from "react";

import { useAuthStatus } from "./api/auth";
import { useMonthUsage } from "./api/queries";
import { ChatView } from "./chat/ChatView";
import { Backdrop } from "./components/Backdrop";
import { ConnectionStatus } from "./components/ConnectionStatus";
import { LoginView } from "./components/LoginView";
import {
  ArrowRightIcon,
  CalendarIcon,
  ChatIcon,
  GaugeIcon,
  MonitorIcon,
  MoonIcon,
  OfficeIcon,
  SunriseIcon,
} from "./components/icons";
import { tr } from "./i18n/tr";
import { href, useRoute, type Route } from "./lib/route";
import { useTheme } from "./lib/theme";
import { DayView } from "./plan/DayView";
import { WeekView } from "./plan/WeekView";
import { budgetTone, money } from "./lib/format";
import { OfficeView } from "./office/OfficeView";
import { StatusView } from "./status/StatusView";
import { SheetView } from "./study/SheetView";

// Takvim holds the Bugün / Yarın / Hafta views (their old links still work).
const CALENDAR: Route[] = ["today", "tomorrow", "week"];
const NAV: { route: Route; label: string; icon: ReactNode; also?: Route[] }[] = [
  { route: "office", label: tr.nav.office, icon: <OfficeIcon /> },
  { route: "chat", label: tr.nav.chat, icon: <ChatIcon /> },
  { route: "today", label: tr.nav.calendar, icon: <CalendarIcon />, also: CALENDAR },
  { route: "status", label: tr.nav.status, icon: <GaugeIcon /> },
];
const CALENDAR_TABS: { route: Route; label: string; icon: ReactNode }[] = [
  { route: "today", label: tr.nav.today, icon: <SunriseIcon width={16} height={16} /> },
  { route: "tomorrow", label: tr.nav.tomorrow, icon: <ArrowRightIcon width={16} height={16} /> },
  { route: "week", label: tr.nav.week, icon: <CalendarIcon width={16} height={16} /> },
];

const isActive = (item: (typeof NAV)[number], route: Route): boolean => item.route === route || !!item.also?.includes(route);

const DesignPreview = lazy(() => import("./design/DesignPreview").then((m) => ({ default: m.DesignPreview })));

export function App() {
  const route = useRoute();
  const auth = useAuthStatus();
  if (auth.isPending) return <Backdrop />;
  if (auth.data?.enabled && !auth.data.authenticated) return <LoginView />;
  if (route === "design-preview") {
    return (
      <Suspense fallback={null}>
        <DesignPreview />
      </Suspense>
    );
  }
  return (
    <div className="flex h-dvh flex-col print:block print:h-auto">
      <Backdrop />
      <Header route={route} />
      <main className="min-h-0 flex-1 overflow-y-auto print:overflow-visible">
        {route === "office" && <OfficeView />}
        {route === "chat" && <ChatView />}
        {CALENDAR.includes(route) && <CalendarTabs route={route} />}
        {route === "today" && <DayView offset={0} />}
        {route === "tomorrow" && <DayView offset={1} />}
        {route === "week" && <WeekView />}
        {route === "status" && <StatusView />}
        {route === "sheet" && <SheetView />}
      </main>
      <BottomNav route={route} />
    </div>
  );
}

function Header({ route }: { route: Route }) {
  const { theme, cycle } = useTheme();
  const themeIcon = { system: <MonitorIcon />, light: <SunriseIcon />, dark: <MoonIcon /> }[theme];
  return (
    <header className="yv-glass border-x-0 border-t-0 pt-[env(safe-area-inset-top)] print:hidden">
      <div className="mx-auto flex h-14 max-w-[1500px] items-center gap-3 px-3 sm:px-6">
        <a href={href("office")} className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <span className="font-grotesk text-xl font-semibold tracking-tight">{tr.appName}</span>
        </a>
        <nav className="ml-4 hidden gap-1 md:flex">
          {NAV.map((item) => (
            <NavLink key={item.route} item={item} active={isActive(item, route)} inline />
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
            className="flex h-10 w-10 items-center justify-center rounded-full text-slate-600 hover:bg-white/60 dark:text-slate-300 dark:hover:bg-white/10"
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
    ok: "yv-glass text-slate-700 dark:text-slate-300",
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
    <nav className="px-3 pb-[max(0.6rem,env(safe-area-inset-bottom))] pt-1 md:hidden print:hidden">
      <ul className="yv-glass grid grid-cols-4 rounded-full p-1">
        {NAV.map((item) => (
          <li key={item.route}>
            <NavLink item={item} active={isActive(item, route)} />
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
    ? "text-indigo-700 dark:text-white"
    : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200";
  if (inline) {
    return (
      <a
        href={href(item.route)}
        aria-current={active ? "page" : undefined}
        className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${color} ${active ? "bg-white/70 shadow-sm dark:bg-white/12" : ""}`}
      >
        {item.label}
      </a>
    );
  }
  return (
    <a
      href={href(item.route)}
      aria-current={active ? "page" : undefined}
      className={`flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-full text-[11px] font-medium transition-colors ${color} ${active ? "bg-white/70 dark:bg-white/12" : ""}`}
    >
      {item.icon}
      {item.label}
    </a>
  );
}

/** Bugün / Yarın / Hafta inside the Takvim tab. */
function CalendarTabs({ route }: { route: Route }) {
  return (
    <nav aria-label={tr.nav.calendar} className="mx-auto flex max-w-3xl justify-center px-3 pt-3 print:hidden">
      <ul className="yv-glass inline-flex gap-1 rounded-full p-1">
        {CALENDAR_TABS.map((tab) => (
          <li key={tab.route}>
            <a
              href={href(tab.route)}
              aria-current={route === tab.route ? "page" : undefined}
              className={`inline-flex min-h-9 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium transition-colors ${
                route === tab.route
                  ? "bg-white/70 text-indigo-700 shadow-sm dark:bg-white/12 dark:text-white"
                  : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              {tab.icon}
              {tab.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
