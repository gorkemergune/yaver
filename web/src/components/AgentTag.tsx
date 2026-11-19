import type { Member } from "../api/types";

/** Coloured name label of a yaver ("Friday"), colour from agents.yaml. */
export function AgentTag({ member, fallback }: { member?: Member; fallback: string }) {
  const color = member?.color ?? "#64748b";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold"
      style={{ color, backgroundColor: `${color}1f` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: color }} aria-hidden />
      {member?.name ?? fallback}
    </span>
  );
}
