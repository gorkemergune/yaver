import type { Member } from "../api/types";
import { AgentTag } from "../components/AgentTag";
import { ChevronIcon } from "../components/icons";
import { tr } from "../i18n/tr";
import { stepSummary, type AgentSteps } from "./model";

/** "Friday 2 değişiklik yaptı ▸" — expands to the tool calls and the yaver's own reply. */
export function Steps({ steps, members }: { steps: AgentSteps[]; members: Record<string, Member> }) {
  if (steps.length === 0) return null;
  return (
    <div className="mt-2 flex flex-col gap-1">
      {steps.map((step) => {
        const summary = stepSummary(step);
        const label =
          summary.kind === "changed"
            ? tr.steps.changed(step.name, summary.count)
            : summary.kind === "asked"
              ? tr.steps.asked(step.name)
              : tr.steps.looked(step.name);
        return (
          <details key={step.agentId} className="yv-inset group rounded-xl">
            <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm text-slate-600 dark:text-slate-300 [&::-webkit-details-marker]:hidden">
              <ChevronIcon width={14} height={14} className="shrink-0 transition-transform group-open:rotate-90" />
              <span className="truncate">{label}</span>
            </summary>
            <div className="space-y-2 px-3 pb-3 text-sm">
              <AgentTag member={members[step.agentId]} fallback={step.name} />
              {step.tools.length > 0 && (
                <ul className="space-y-0.5 text-slate-600 dark:text-slate-300">
                  {step.tools.map((tool, index) => (
                    <li key={`${tool.tool}-${String(index)}`} className="flex gap-2">
                      <span aria-hidden>{tool.error ? "⚠" : tool.mutates ? "✎" : "·"}</span>
                      <span>
                        {tr.tools[tool.tool] ?? tool.tool}
                        {tool.error && (
                          <span className="text-rose-600 dark:text-rose-400"> ({tr.steps.failed})</span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {step.reply && <p className="text-slate-700 dark:text-slate-200">{step.reply}</p>}
            </div>
          </details>
        );
      })}
    </div>
  );
}
