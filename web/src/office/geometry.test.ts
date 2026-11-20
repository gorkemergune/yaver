import { describe, expect, it } from "vitest";

import layout from "./scene/layout.json";
import { DESK_X, OBST, SPOTS, at, clearPt, figureZ, routeFrom, spotOf, type Point } from "./geometry";

function distToSegment(p: Point, a: Point, b: Point): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = dx * dx + dy * dy;
  const t = len === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

/** Points of the walk (sampled every 0.02 tiles) inside furniture or off the floor. Only
 *  the short legs between a seat and its approach point may cross the seat's own chair. */
function violations(fromKey: string, toKey: string): Point[] {
  const from = spotOf(fromKey);
  const to = spotOf(toKey);
  const route = [from.pt, ...routeFrom(null, fromKey, toKey)];
  const bad: Point[] = [];
  for (let i = 1; i < route.length; i++) {
    const a = at(route, i - 1);
    const b = at(route, i);
    const n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / 0.02));
    for (let k = 0; k <= n; k++) {
      const p: Point = [a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n];
      if (clearPt(p, 0)) continue;
      const seatLeg = distToSegment(p, from.pt, from.app) < 1e-6 || distToSegment(p, to.app, to.pt) < 1e-6;
      if (!seatLeg) bad.push(p);
    }
  }
  return bad;
}

describe("walking", () => {
  const keys = Object.keys(SPOTS);

  it("has every seat, meeting, coffee and walk spot", () => {
    // 11 seats (Yaver's room + 2 rows x 5 desks), 9 meeting, 7 coffee, 8 walk
    expect(keys).toHaveLength(35);
    for (const key of keys) expect(clearPt(spotOf(key).app, 0), `${key} approach point`).toBe(true);
  });

  it("no route between any two spots passes through furniture", () => {
    let routes = 0;
    const failures: string[] = [];
    for (const from of keys) {
      for (const to of keys) {
        if (from === to) continue;
        routes++;
        const bad = violations(from, to);
        if (bad.length) failures.push(`${from} -> ${to}: ${String(bad.length)} points, e.g. ${JSON.stringify(bad[0])}`);
      }
    }
    expect(routes).toBe(35 * 34);
    expect(failures).toEqual([]);
  });

  it("routes end on the target and move in short steps", () => {
    const route = routeFrom(null, "seat:back:0", "coffee:0");
    expect(route[route.length - 1]).toEqual(spotOf("coffee:0").pt);
    for (let i = 1; i < route.length - 1; i++) {
      const a = at(route, i - 1);
      const b = at(route, i);
      expect(Math.hypot(b[0] - a[0], b[1] - a[1])).toBeLessThanOrEqual(0.55 + 1e-9);
    }
  });

  it("a walk can be redirected from where the figure is", () => {
    const pos: Point = [6.5, 7.0];
    const route = routeFrom(pos, null, "meet:0");
    expect(route[route.length - 1]).toEqual(spotOf("meet:0").pt);
  });
});

describe("scene layout", () => {
  it("desk chairs in the obstacle list follow the desk columns of the scene script", () => {
    expect(DESK_X).toEqual(layout.deskX);
    for (const x of layout.deskX) {
      expect(OBST).toContainEqual([x + 0.48, 3.0, x + 0.92, 3.42]);
      expect(OBST).toContainEqual([x + 0.48, 5.9, x + 0.92, 6.32]);
    }
  });

  it("figures sit between the static layers as in the prototype", () => {
    const z = Object.fromEntries(layout.layers.map((l) => [l.name, l.z]));
    const seat = (key: string): number => {
      const p = spotOf(key).pt;
      return figureZ(p[0], p[1]);
    };
    // Yaver behind its desk and its glass wall
    expect(seat("seat:office")).toBeLessThan(z.yaverDesk ?? 0);
    // back row behind the desks, front row in front of them but under its chair backs
    expect(seat("seat:back:4")).toBeLessThan(z.desks ?? 0);
    expect(seat("seat:front:0")).toBeGreaterThan(z.desksFront ?? 0);
    expect(seat("seat:front:4")).toBeLessThan(z.chairBacks ?? 0);
    // meeting room: under its front glass / chair backs
    expect(seat("meet:5")).toBeLessThan(z.glassM ?? 0);
    expect(seat("meet:0")).toBeGreaterThan(z.desks ?? 0);
  });
});
