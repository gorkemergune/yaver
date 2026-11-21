import { useEffect, useRef, useState } from "react";

import { planFigures, stepFigures, type Figure, type Staff } from "./model";

// One step (0.55 tiles, the prototype's) per tick, twice the prototype's pace; the CSS
// transition (office.css) has the same length.
export const TICK_MS = 450;

/** Figures that follow `staff`: every tick re-plans (a new state = a new route) and takes
 *  one step, so a change shows within a tick. */
export function useFigures(staff: Staff): Record<string, Figure> {
  const [figures, setFigures] = useState<Record<string, Figure>>({});
  const latest = useRef(staff);

  useEffect(() => {
    latest.current = staff;
  }, [staff]);

  useEffect(() => {
    const tick = (): void => {
      const now = Date.now();
      setFigures((prev) => stepFigures(planFigures(prev, latest.current, now), now));
    };
    const first = window.setTimeout(tick, 0); // the snapshot's people appear at once
    const timer = window.setInterval(tick, TICK_MS);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, []);

  // a snapshot arriving later: place people without waiting for the next tick
  const empty = Object.keys(figures).length === 0;
  const hasStaff = Object.keys(staff).length > 0;
  useEffect(() => {
    if (!empty || !hasStaff) return;
    const now = window.setTimeout(() => {
      setFigures((prev) => planFigures(prev, latest.current, Date.now()));
    }, 0);
    return () => {
      window.clearTimeout(now);
    };
  }, [empty, hasStaff]);

  return figures;
}
