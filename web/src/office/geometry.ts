/**
 * Office geometry, ported from the approved prototype (design/office-prototype/Main.dc.html):
 * isometric projection, obstacles, the walking grid + A*, seats / approach points and the
 * z-order rule. Numbers are the prototype's; the static layers come from
 * scripts/office_scene.py (scene/layout.json), which must stay in step with OBST below.
 *
 * Seats are keyed by desk ("seat:back:0"), not by employee: who sits where comes from
 * agents.yaml (the backend's `desk`).
 */
import layout from "./scene/layout.json";

export type Point = [number, number];

/** items[i]; the indexes used here are always in range (RangeError otherwise). */
export function at<T>(items: readonly T[], i: number): T {
  const item = items[i];
  if (item === undefined) throw new RangeError(`index ${String(i)} of ${String(items.length)}`);
  return item;
}

/** A value that must be there (RangeError otherwise). */
export function need<T>(value: T | null | undefined, what: string): T {
  if (value === null || value === undefined) throw new RangeError(`missing ${what}`);
  return value;
}

export const [TW = 32, TH = 16] = layout.tile;
export const [OX = 480, OY = 150] = layout.origin;
export const SCENE_W = layout.width;
export const SCENE_H = layout.height;
export const DESK_X: readonly number[] = layout.deskX;
export const DESK_COLUMNS = DESK_X.length;

export function iso(x: number, y: number): { X: number; Y: number } {
  return { X: OX + (x - y) * TW, Y: OY + (x + y) * TH };
}

// ---------- walkable grid + A* (figures never pass through furniture) ----------
export const CELL = 0.25;
export const GW = 48;
export const GH = 40;
const PAD = 0.16;
/** Walkable floor: x 0.2..11.92, y 0.2..9.8 (tiles). */
export const BOUNDS = { minX: 0.2, minY: 0.2, maxX: 11.92, maxY: 9.8 } as const;

/** Furniture and walls as [x1, y1, x2, y2] rectangles in tiles. */
export const OBST: readonly (readonly [number, number, number, number])[] = (() => {
  const o: [number, number, number, number][] = [
    [0, 0.55, 2.95, 0.65], [2.85, 0.6, 2.95, 3.85], [0, 3.75, 0.9, 3.85], [1.8, 3.75, 2.95, 3.85],
    [0, 0.8, 0.4, 2.1], [0.1, 3.2, 0.45, 3.55], [0.75, 1.4, 2.15, 2.15], [1.23, 0.95, 1.67, 1.37], [1.1, 2.6, 1.6, 3.1], [1.9, 2.6, 2.4, 3.1],
    [0, 5.3, 3.65, 5.4], [3.55, 5.35, 3.65, 7.5], [3.55, 8.4, 3.65, 9.85],
    [0.9, 6.6, 3.3, 7.8], [0.3, 9.0, 2.9, 9.6], [3.15, 9.35, 3.5, 9.7],
    [4.3, 3.9, 11.42, 5.3],
    [7.4, 0, 10.5, 0.65], [10.6, 0, 11.4, 0.75], [11.5, 0.1, 11.92, 0.52], [8.2, 1.35, 9.4, 1.8],
    [4.3, 0.12, 4.9, 0.74], [5.25, 0.12, 5.85, 0.74], [6.2, 0.12, 6.8, 0.74], [5.0, 0.3, 5.2, 0.5], [5.95, 0.3, 6.15, 0.5],
    [8.9, 7.6, 11.1, 8.2], [9.4, 8.65, 10.6, 9.15], [11.5, 9.35, 11.85, 9.7], [6.5, 9.4, 6.85, 9.75], [7.0, 7.9, 8.75, 8.0],
  ];
  // meeting room chairs, both sides of the table
  for (const x of [1.2, 2.0, 2.8]) {
    o.push([x - 0.21, 6.03, x + 0.23, 6.45]);
    o.push([x - 0.21, 7.98, x + 0.23, 8.4]);
  }
  // desk chairs: back row (y 3.0) and front row (y 5.9) of every desk pair
  for (const x of DESK_X) {
    o.push([x + 0.48, 3.0, x + 0.92, 3.42]);
    o.push([x + 0.48, 5.9, x + 0.92, 6.32]);
  }
  return o;
})();

const BLOCK: boolean[][] = (() => {
  const rows: boolean[][] = [];
  for (let gy = 0; gy < GH; gy++) {
    const row: boolean[] = [];
    for (let gx = 0; gx < GW; gx++) {
      const cx = (gx + 0.5) * CELL;
      const cy = (gy + 0.5) * CELL;
      let b = cx < BOUNDS.minX || cy < BOUNDS.minY || cx > BOUNDS.maxX || cy > BOUNDS.maxY;
      for (let k = 0; !b && k < OBST.length; k++) {
        const ob = OBST[k];
        if (ob && cx > ob[0] - PAD && cx < ob[2] + PAD && cy > ob[1] - PAD && cy < ob[3] + PAD) b = true;
      }
      row.push(b);
    }
    rows.push(row);
  }
  return rows;
})();

const blocked = (x: number, y: number): boolean => BLOCK[y]?.[x] ?? true;

function cellOf(p: Point): Point {
  return [Math.max(0, Math.min(GW - 1, Math.floor(p[0] / CELL))), Math.max(0, Math.min(GH - 1, Math.floor(p[1] / CELL)))];
}

function centerOf(c: Point): Point {
  return [(c[0] + 0.5) * CELL, (c[1] + 0.5) * CELL];
}

function nearestFree(c: Point): Point {
  if (!blocked(c[0], c[1])) return c;
  for (let r = 1; r < 8; r++) {
    for (let dy = -r; dy <= r; dy++) {
      for (let dx = -r; dx <= r; dx++) {
        const x = c[0] + dx;
        const y = c[1] + dy;
        if (x >= 0 && y >= 0 && x < GW && y < GH && !blocked(x, y)) return [x, y];
      }
    }
  }
  return c;
}

/** The point is on the floor and at least `margin` tiles away from every obstacle. */
export function clearPt(p: Point, margin: number): boolean {
  if (p[0] < BOUNDS.minX || p[1] < BOUNDS.minY || p[0] > BOUNDS.maxX || p[1] > BOUNDS.maxY) return false;
  for (const o of OBST) {
    if (p[0] > o[0] - margin && p[0] < o[2] + margin && p[1] > o[1] - margin && p[1] < o[3] + margin) return false;
  }
  return true;
}

function lineFree(a: Point, b: Point): boolean {
  const d = Math.hypot(b[0] - a[0], b[1] - a[1]);
  const n = Math.max(1, Math.ceil(d / 0.03));
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    if (!clearPt([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], 0.09)) return false;
  }
  return true;
}

export function astar(from: Point, to: Point): Point[] {
  const s = nearestFree(cellOf(from));
  const g = nearestFree(cellOf(to));
  const key = (c: Point): number => c[1] * GW + c[0];
  const open: Point[] = [s];
  const came = new Map<number, Point>();
  const gs = new Map<number, number>([[key(s), 0]]);
  const fs = new Map<number, number>([[key(s), Math.hypot(g[0] - s[0], g[1] - s[1])]]);
  const closed = new Set<number>();
  let guard = 0;
  while (open.length && guard++ < 4000) {
    let bi = 0;
    for (let i = 1; i < open.length; i++) {
      if ((fs.get(key(at(open, i))) ?? Infinity) < (fs.get(key(at(open, bi))) ?? Infinity)) bi = i;
    }
    const cur = at(open.splice(bi, 1), 0);
    const ck = key(cur);
    if (cur[0] === g[0] && cur[1] === g[1]) {
      const out: Point[] = [cur];
      for (let prev = came.get(key(cur)); prev; prev = came.get(key(prev))) out.unshift(prev);
      return out.map(centerOf);
    }
    closed.add(ck);
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dy) continue;
        const nx = cur[0] + dx;
        const ny = cur[1] + dy;
        if (nx < 0 || ny < 0 || nx >= GW || ny >= GH || blocked(nx, ny)) continue;
        if (dx && dy && (blocked(nx, cur[1]) || blocked(cur[0], ny))) continue; // no corner cutting
        const nk = ny * GW + nx;
        if (closed.has(nk)) continue;
        const ng = (gs.get(ck) ?? 0) + (dx && dy ? 1.414 : 1);
        const known = gs.get(nk);
        if (known === undefined || ng < known) {
          gs.set(nk, ng);
          fs.set(nk, ng + Math.hypot(g[0] - nx, g[1] - ny));
          came.set(nk, cur);
          if (!open.some((c) => c[0] === nx && c[1] === ny)) open.push([nx, ny]);
        }
      }
    }
  }
  return [centerOf(s), centerOf(g)];
}

function smooth(pts: Point[]): Point[] {
  if (pts.length < 3) return pts;
  const out: Point[] = [at(pts, 0)];
  let i = 0;
  while (i < pts.length - 1) {
    let j = pts.length - 1;
    while (j > i + 1 && !lineFree(at(pts, i), at(pts, j))) j--;
    out.push(at(pts, j));
    i = j;
  }
  return out;
}

function steps(pts: Point[], maxStep: number): Point[] {
  const out: Point[] = [];
  for (let i = 1; i < pts.length; i++) {
    const a = at(pts, i - 1);
    const b = at(pts, i);
    const d = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const n = Math.max(1, Math.ceil(d / maxStep));
    for (let k = 1; k <= n; k++) out.push([a[0] + ((b[0] - a[0]) * k) / n, a[1] + ((b[1] - a[1]) * k) / n]);
  }
  return out;
}

// ---------- spots: where figures stand or sit ----------
export interface Sit {
  elev: number; // seat height in px
  back: boolean; // seen from behind (front desk row, far side of the meeting table)
}
export interface Spot {
  pt: Point; // where the figure ends up
  app: Point; // approach point on the walkable floor
  sit: Sit | null;
}

export type DeskRow = "office" | "back" | "front";
export const seatKey = (row: DeskRow, col: number): string => (row === "office" ? "seat:office" : `seat:${row}:${String(col)}`);

const MEET: [number, number, number, boolean, number][] = [
  [1.21, 6.24, 14, false, 5.66], [2.01, 6.24, 14, false, 5.66], [2.81, 6.24, 14, false, 5.66],
  [1.03, 8.19, 14, true, 8.66], [1.83, 8.19, 14, true, 8.66], [2.63, 8.19, 14, true, 8.66],
  [0.65, 9.35, 12, false, 8.66], [1.6, 9.35, 12, false, 8.66], [2.55, 9.35, 12, false, 8.66],
];
const COFFEE: number[][] = [[7.95, 1.05], [9.75, 1.05], [10.15, 1.2], [8.6, 2.15], [4.6, 0.5, 1.05], [5.55, 0.5, 1.05], [6.5, 0.5, 1.05]];
const WALK: number[][] = [[9.35, 7.95, 8.42, 1], [10.25, 7.95, 8.42, 1], [6.5, 8.0], [5.0, 8.8], [7.2, 2.2], [11.7, 6.6], [11.0, 9.4], [3.4, 4.6]];
// Standing room for the standup (Yaver + 9 employees > 9 seats): by the screen and the door.
const STAND: Point[] = [[0.45, 7.0], [0.45, 7.6], [3.3, 5.75]];
export const MEET_COUNT = MEET.length + STAND.length;
/** Table seats (0-2 near side, 3-5 across); 6-8 are the sofa; 9-11 standing. */
export const MEET_TABLE_SIDE = 3;
export const COFFEE_COUNT = COFFEE.length;
export const WALK_COUNT = WALK.length;

/** Where people come in and go home (the corridor on the right): an employee outside
 *  office hours (`off`) walks here and is gone until a request brings it back. */
export const DOOR = "door";

export const SPOTS: Readonly<Record<string, Spot>> = (() => {
  const spots: Record<string, Spot> = {};
  const spot = (key: string, pt: Point, app: Point | null = null, sit: Sit | null = null): void => {
    spots[key] = { pt, app: app ?? pt, sit };
  };
  spot(DOOR, [11.7, 6.6]);
  spot("seat:office", [1.45, 1.16], [2.5, 1.16], { elev: 14, back: false });
  DESK_X.forEach((dx, col) => {
    const x = dx + 0.7;
    spot(seatKey("back", col), [x, 3.21], [x, 2.68], { elev: 14, back: false });
    spot(seatKey("front", col), [x - 0.18, 6.11], [x - 0.18, 6.64], { elev: 14, back: true });
  });
  MEET.forEach(([x, y, elev, back, appY], i) => {
    const appX = y > 9 ? (x < 1 ? 0.62 : x < 2 ? 1.62 : 2.42) : x + (y < 7 ? 0.01 : 0.18);
    spot(`meet:${String(i)}`, [x, y], [appX, appY], { elev, back });
  });
  STAND.forEach((pt, i) => {
    spot(`meet:${String(MEET.length + i)}`, pt);
  });
  COFFEE.forEach((c, i) => {
    const [x = 0, y = 0, appY] = c;
    spot(`coffee:${String(i)}`, [x, y], appY ? [x, appY] : null, appY ? { elev: 12, back: false } : null);
  });
  WALK.forEach((w, i) => {
    const [x = 0, y = 0, appY, seated] = w;
    spot(`walk:${String(i)}`, [x, y], appY ? [x, appY] : null, seated ? { elev: 12, back: false } : null);
  });
  return spots;
})();

export function spotOf(key: string): Spot {
  const found = SPOTS[key];
  if (!found) throw new Error(`unknown spot ${key}`);
  return found;
}

/**
 * The steps (0.55 tiles each) from a spot - or from a point mid-walk (`fromKey` null) - to a
 * spot: out to the approach point, A* + smoothing across the floor, in to the seat.
 */
export function routeFrom(pos: Point | null, fromKey: string | null, toKey: string): Point[] {
  const b = spotOf(toKey);
  const fromSpot = fromKey ? spotOf(fromKey) : null;
  const origin = fromSpot ? fromSpot.pt : need(pos, "position of a walking figure");
  const start: Point = fromSpot ? fromSpot.app : origin;
  const mid = smooth(astar(start, b.app));
  let chain: Point[] = [origin, start, ...mid, b.app];
  chain = chain.filter((p, i) => {
    const prev = chain[i - 1];
    return i === 0 || !prev || Math.hypot(p[0] - prev[0], p[1] - prev[1]) > 0.01;
  });
  const pts = steps(chain, 0.55);
  pts.push(b.pt);
  return pts;
}

// ---------- desks ----------
const [DESK_W = 1.4, DESK_D = 0.7] = layout.desk;
const DESK_TOP_Z = 22; // desk top (scripts/office_scene.py desk())
const SCREEN_TOP_Z = 48; // a little above the monitors

const px = (x: number, y: number, h: number): string => {
  const p = iso(x, y);
  return `${p.X.toFixed(1)},${(p.Y - h).toFixed(1)}`;
};

/** The outline of a desk with its monitors (an SVG polygon): the dark screen at night,
 *  the click target for the zoomed screen. */
export function deskOutline(row: "back" | "front", col: number): string {
  const x = at(DESK_X, col);
  const y = layout.rowY[row];
  const [w, d] = [DESK_W, DESK_D];
  return [
    px(x, y, SCREEN_TOP_Z),
    px(x + w, y, SCREEN_TOP_Z),
    px(x + w, y, DESK_TOP_Z),
    px(x + w, y + d, DESK_TOP_Z),
    px(x, y + d, DESK_TOP_Z),
    px(x, y + d, SCREEN_TOP_Z),
  ].join(" ");
}

/** The middle of a desk on the stage (px): where the zoomed screen grows from. */
export function deskCenter(row: "office" | "back" | "front", col: number): { X: number; Y: number } {
  if (row === "office") {
    const p = iso(1.45, 1.95);
    return { X: p.X, Y: p.Y - 34 };
  }
  const p = iso(at(DESK_X, col) + DESK_W / 2, layout.rowY[row] + DESK_D / 2);
  return { X: p.X, Y: p.Y - 34 };
}

// ---------- drawing order ----------
/** Inside the meeting room's glass walls. */
export const inMeetingRoom = (x: number, y: number): boolean => x < 3.6 && y > 5.35;

/**
 * z-index of a figure: 400 behind the back desks, 520 in the meeting room (under its front
 * glass and chair backs), 600 between the desk rows (under the front-row chair backs),
 * 700 in front of everything; deeper in the room = lower within a band.
 */
export function figureZ(x: number, y: number): number {
  const base = inMeetingRoom(x, y) ? 520 : y < 4.25 ? 400 : y < 6.3 ? 600 : 700;
  return base + Math.round((x + y) * 2);
}

/** Top-left of the 28x46 figure box: standing on the floor or sitting on a seat. */
export function figureBox(x: number, y: number, sit: Sit | null): { left: number; top: number } {
  const p = iso(x, y);
  return { left: Math.round(p.X - 14), top: Math.round(sit ? p.Y - sit.elev - 35 : p.Y - 44) };
}
