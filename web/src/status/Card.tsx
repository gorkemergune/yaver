import type { ReactNode } from "react";

/** A glass card with a title (status page sections). */
export function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="yv-glass yv-rise rounded-3xl p-4">
      <h2 className="font-grotesk mb-3 text-lg font-semibold tracking-tight">{title}</h2>
      {children}
    </section>
  );
}
