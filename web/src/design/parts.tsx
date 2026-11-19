import type { CSSProperties, ReactNode } from "react";

import type { PreviewMember, Role } from "./mock";

const ICONS: Record<Role, ReactNode> = {
  // compass-sparkle: the coordinator
  coordinator: <path d="M12 3v3m0 12v3M3 12h3m12 0h3M7.8 7.8l1.4 1.4m5.6 5.6 1.4 1.4m0-8.4-1.4 1.4m-5.6 5.6-1.4 1.4M12 9.5l1.2 1.3 1.3 1.2-1.3 1.2L12 14.5l-1.2-1.3L9.5 12l1.3-1.2z" />,
  // graduation cap: classes
  academic: <path d="m2 9 10-5 10 5-10 5zm4 2.2V16c0 1.6 2.7 3 6 3s6-1.4 6-3v-4.8M22 9v5" />,
  // calendar clock: agenda
  agenda: <path d="M8 2v3m8-3v3M3.5 9h17M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v4M5 4.5A1.5 1.5 0 0 0 3.5 6v13A1.5 1.5 0 0 0 5 20.5h6M17 14v3l2 1m3-1a5 5 0 1 1-10 0 5 5 0 0 1 10 0z" />,
  // flame: discipline
  discipline: <path d="M12 21a6 6 0 0 0 6-6c0-3.5-2.5-5.5-3.5-8-.6 1.8-1.6 2.8-2.7 3.3C12 7.6 10.8 5 8.5 3c.4 3-3 6-3 11a6.5 6.5 0 0 0 6.5 7zm0 0a2.5 2.5 0 0 0 2.5-2.5c0-1.6-1.3-2.4-1.8-3.6-.6 1-1.4 1.5-2.2 1.8A2.5 2.5 0 0 0 12 21z" />,
};

export function RoleIcon({ role, size = 18 }: { role: Role; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {ICONS[role]}
    </svg>
  );
}

/** A yaver's avatar: its icon on its own color. `shape` differs per design variant. */
export function Avatar({ member, shape, size = 36 }: { member: PreviewMember; shape: "orb" | "tile"; size?: number }) {
  const style: CSSProperties =
    shape === "orb"
      ? {
          width: size,
          height: size,
          background: `radial-gradient(circle at 30% 25%, ${member.color}ee, ${member.color}88 55%, ${member.color}44)`,
          boxShadow: `0 0 0 1px ${member.color}66, 0 6px 22px -6px ${member.color}aa`,
        }
      : {
          width: size,
          height: size,
          background: `${member.color}26`,
          color: member.color,
          boxShadow: `inset 0 0 0 1px ${member.color}55`,
        };
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center ${shape === "orb" ? "rounded-full text-white" : "rounded-[30%]"}`}
      style={style}
      title={member.name}
    >
      <RoleIcon role={member.role} size={Math.round(size * 0.5)} />
    </span>
  );
}

/** "yazıyor" dots in the yaver's color. */
export function TypingDots({ color }: { color: string }) {
  return (
    <span className="inline-flex items-center gap-1" role="status" aria-label="yazıyor">
      {[0, 1, 2].map((i) => (
        <span key={i} className="yv-dot h-1.5 w-1.5 rounded-full" style={{ background: color, animationDelay: `${String(i * 160)}ms` }} />
      ))}
    </span>
  );
}

/** Children rise in one after another (replayed when `play` changes). */
export function Rise({ index, children, className = "" }: { index: number; children: ReactNode; className?: string }) {
  return (
    <div className={`yv-rise ${className}`} style={{ animationDelay: `${String(80 + index * 90)}ms` }}>
      {children}
    </div>
  );
}
