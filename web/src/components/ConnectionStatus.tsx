import { useReadiness } from "../api/health";
import { tr } from "../i18n/tr";

export function ConnectionStatus() {
  const { data, isPending, isError } = useReadiness();

  const state = isPending ? "checking" : !isError && data?.status === "ok" ? "online" : "offline";
  const dotClass = {
    checking: "bg-amber-400",
    online: "bg-emerald-500",
    offline: "bg-rose-500",
  }[state];

  return (
    <span className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
      <span className={`h-2 w-2 rounded-full ${dotClass}`} aria-hidden />
      {tr.connection[state]}
    </span>
  );
}
