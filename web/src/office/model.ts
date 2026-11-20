/**
 * The office as data: what the backend says (OfficeEvent -> Staff) and where each figure
 * goes because of it (Staff -> Figure). Pure functions, tested; the React side only
 * ticks them.
 *
 *   working        -> walks to its own desk, sits, "…" bubble
 *   meeting        -> meeting room; with `meeting_with`, both at the same table, facing
 *   break          -> idle: coffee, an armchair, the lounge (picked here, at random)
 *   needs_user     -> red dot, wherever it is
 *
 * working / meeting / needs_user come only from the backend; idle places are the only
 * thing the web app chooses.
 */
import type { EmployeeState, OfficeEmployee, OfficeEvent } from "../api/types";
import { tr } from "../i18n/tr";
import {
  COFFEE_COUNT,
  MEET_COUNT,
  MEET_TABLE_SIDE,
  SPOTS,
  WALK_COUNT,
  figureBox,
  figureZ,
  routeFrom,
  seatKey,
  type Point,
} from "./geometry";

export type Staff = Record<string, OfficeEmployee>;

/** One SSE event applied to the known employees. */
export function applyOfficeEvent(staff: Staff, event: OfficeEvent): Staff {
  if (event.type === "snapshot") {
    return event.ready ? Object.fromEntries(event.employees.map((e) => [e.id, e])) : {};
  }
  if (event.type === "state") {
    const current = staff[event.employee_id];
    if (!current) return staff; // not in the office yet: the next snapshot brings it
    const { activity, task, tool, meeting_with, needs_user, needs_user_reason, since, ts } = event;
    const state = { activity, task, tool, meeting_with, needs_user, needs_user_reason, since, ts };
    return { ...staff, [event.employee_id]: { ...current, ...state } };
  }
  return staff;
}

// ---------- figures ----------

export type Act = "work" | "meeting" | "coffee" | "walk" | "home" | "off";
const IDLE: readonly Act[] = ["coffee", "walk", "home"];

export interface Figure {
  id: string;
  spot: string; // where it is or is walking to
  act: Act;
  x: number;
  y: number;
  path: Point[]; // the steps still to walk, one per tick
  cup: boolean;
  idleUntil: number; // ms; when an idle figure picks a new place
}

export type Random = () => number;

export const homeSpot = (e: OfficeEmployee): string => seatKey(e.desk.row, e.desk.col);

const IDLE_MIN_MS = 25_000;
const IDLE_SPAN_MS = 35_000;

function freeOf(prefix: string, count: number, taken: Set<string>, random: Random): string | null {
  const free: string[] = [];
  for (let i = 0; i < count; i++) if (!taken.has(`${prefix}${String(i)}`)) free.push(`${prefix}${String(i)}`);
  return free.length ? (free[Math.floor(random() * free.length)] ?? null) : null;
}

/** Meeting room seats: a pair (`meeting_with` both ways or one way) shares the table, the
 *  coordinator on the near side facing us, the other across; a lone meeting takes any. */
export function meetingSeats(staff: Staff, figures: Record<string, Figure>): Record<string, string> {
  const meeting = Object.values(staff)
    .filter((e) => e.activity === "meeting")
    .sort((a, b) => Number(b.is_coordinator) - Number(a.is_coordinator) || a.id.localeCompare(b.id));
  const seats: Record<string, string> = {};
  const taken = new Set<string>();
  const pairs: [OfficeEmployee, OfficeEmployee][] = [];
  const paired = new Set<string>();
  for (const e of meeting) {
    if (paired.has(e.id)) continue;
    const partner = meeting.find((o) => o.id !== e.id && !paired.has(o.id) && (e.meeting_with === o.id || o.meeting_with === e.id));
    if (partner) {
      pairs.push([e, partner]);
      paired.add(e.id).add(partner.id);
    }
  }
  const singles = meeting.filter((e) => !paired.has(e.id));
  const tableSeat = (spot: string | undefined): number | null => {
    const m = /^meet:(\d+)$/.exec(spot ?? "");
    const n = m ? Number(m[1]) : NaN;
    return n < 2 * MEET_TABLE_SIDE ? n : null;
  };
  // keep pairs already seated across from each other
  const open: [OfficeEmployee, OfficeEmployee][] = [];
  for (const [a, b] of pairs) {
    const sa = tableSeat(figures[a.id]?.spot);
    const sb = tableSeat(figures[b.id]?.spot);
    if (sa !== null && sb !== null && Math.abs(sa - sb) === MEET_TABLE_SIDE) {
      const near = `meet:${String(sa)}`;
      const far = `meet:${String(sb)}`;
      seats[a.id] = near;
      seats[b.id] = far;
      taken.add(near).add(far);
    } else open.push([a, b]);
  }
  for (const [a, b] of open) {
    for (let j = 0; j < MEET_TABLE_SIDE; j++) {
      const near = `meet:${String(j)}`;
      const far = `meet:${String(j + MEET_TABLE_SIDE)}`;
      if (taken.has(near) || taken.has(far)) continue;
      seats[a.id] = near;
      seats[b.id] = far;
      taken.add(near).add(far);
      break;
    }
  }
  for (const e of [...singles, ...open.flat().filter((e) => !seats[e.id])]) {
    const kept = figures[e.id]?.spot;
    if (kept?.startsWith("meet:") && !taken.has(kept)) {
      seats[e.id] = kept;
    } else {
      for (let i = 0; i < MEET_COUNT; i++) {
        if (!taken.has(`meet:${String(i)}`)) {
          seats[e.id] = `meet:${String(i)}`;
          break;
        }
      }
    }
    const seat = seats[e.id];
    if (seat) taken.add(seat);
  }
  return seats;
}

interface Target {
  act: Act;
  spot: string;
}

function idleTarget(e: OfficeEmployee, taken: Set<string>, random: Random): Target {
  const home = { act: "home" as const, spot: homeSpot(e) };
  const r = random();
  if (e.is_coordinator) {
    // Yaver mostly stays in its room; now and then a coffee
    if (r < 0.8) return home;
    const coffee = freeOf("coffee:", COFFEE_COUNT, taken, random);
    return coffee ? { act: "coffee", spot: coffee } : home;
  }
  const order: ["coffee" | "walk", string, number][] =
    r < 0.55 ? [["coffee", "coffee:", COFFEE_COUNT], ["walk", "walk:", WALK_COUNT]] : [["walk", "walk:", WALK_COUNT], ["coffee", "coffee:", COFFEE_COUNT]];
  for (const [act, prefix, count] of order) {
    const spot = freeOf(prefix, count, taken, random);
    if (spot) return { act, spot };
  }
  return home;
}

function go(f: Figure, target: Target): Figure {
  if (f.spot === target.spot && !f.path.length) return { ...f, act: target.act, cup: target.act === "coffee" };
  const path = f.path.length ? routeFrom([f.x, f.y], null, target.spot) : routeFrom(null, f.spot, target.spot);
  return { ...f, spot: target.spot, act: target.act, path, cup: f.act === "coffee" || target.act === "coffee" };
}

function place(e: OfficeEmployee, target: Target, now: number, random: Random): Figure {
  const spot = SPOTS[target.spot];
  const [x, y] = spot ? spot.pt : [0, 0];
  return { id: e.id, spot: target.spot, act: target.act, x, y, path: [], cup: target.act === "coffee", idleUntil: now + IDLE_MIN_MS + random() * IDLE_SPAN_MS };
}

/**
 * Sends every figure where its employee's state says (new figures appear there without
 * walking). Idle figures keep their place until `idleUntil`, then pick another.
 */
export function planFigures(figures: Record<string, Figure>, staff: Staff, now: number, random: Random = Math.random): Record<string, Figure> {
  const seats = meetingSeats(staff, figures);
  const taken = new Set<string>(Object.values(seats));
  const next: Record<string, Figure> = {};
  // non-idle first: their places are fixed; idle figures avoid the spots they hold
  const ordered = Object.values(staff).sort((a, b) => Number(a.activity === "break") - Number(b.activity === "break"));
  for (const f of Object.values(figures)) if (staff[f.id] && IDLE.includes(f.act)) taken.add(f.spot);
  for (const e of ordered) {
    const f = figures[e.id];
    let target: Target;
    if (e.activity === "working") target = { act: "work", spot: homeSpot(e) };
    else if (e.activity === "off") target = { act: "off", spot: homeSpot(e) };
    else if (e.activity === "meeting") target = { act: "meeting", spot: seats[e.id] ?? homeSpot(e) };
    else if (f && IDLE.includes(f.act) && f.idleUntil > now) target = { act: f.act, spot: f.spot };
    else {
      if (f) taken.delete(f.spot);
      target = idleTarget(e, taken, random);
    }
    taken.add(target.spot);
    if (!f) {
      next[e.id] = place(e, target, now, random);
      continue;
    }
    let moved = go(f, target);
    if (IDLE.includes(target.act) && !(IDLE.includes(f.act) && f.idleUntil > now)) {
      moved = { ...moved, idleUntil: now + IDLE_MIN_MS + random() * IDLE_SPAN_MS };
    }
    next[e.id] = moved;
  }
  return next;
}

/** One tick (0.9 s): every walking figure takes its next step. */
export function stepFigures(figures: Record<string, Figure>): Record<string, Figure> {
  let changed = false;
  const next: Record<string, Figure> = {};
  for (const [id, f] of Object.entries(figures)) {
    if (!f.path.length) {
      next[id] = f;
      continue;
    }
    changed = true;
    const [p, ...rest] = f.path as [Point, ...Point[]];
    next[id] = { ...f, x: p[0], y: p[1], path: rest, cup: rest.length ? f.cup : f.act === "coffee" };
  }
  return changed ? next : figures;
}

// ---------- what is drawn ----------

export interface FigureView {
  left: number;
  top: number;
  z: number;
  sitting: boolean;
  fromBehind: boolean; // front desk row and the far side of the meeting table
  walking: boolean;
  atDesk: boolean; // working at its desk: the "…" bubble
  hasCup: boolean;
  alert: boolean; // needs_user: red dot
  status: string;
}

export function figureView(f: Figure, e: OfficeEmployee, staff: Staff): FigureView {
  const walking = f.path.length > 0;
  const spot = SPOTS[f.spot];
  const sit = !walking && spot?.sit ? spot.sit : null;
  const { left, top } = figureBox(f.x, f.y, sit);
  return {
    left,
    top,
    z: figureZ(f.x, f.y),
    sitting: !!sit,
    fromBehind: !!sit?.back,
    walking,
    atDesk: f.act === "work" && !walking,
    hasCup: f.cup || (f.act === "coffee" && !walking),
    alert: e.needs_user,
    status: statusText(f, e, staff),
  };
}

export function statusText(f: Figure, e: OfficeEmployee, staff: Staff): string {
  const s = tr.office.status;
  if (f.path.length > 0) {
    return f.act === "work" ? s.toDesk : f.act === "coffee" ? s.toKitchen : f.act === "meeting" ? s.toMeeting : s.walking;
  }
  if (e.needs_user && e.activity !== "working") return e.needs_user_reason === "budget" ? s.budget : s.waiting;
  switch (f.act) {
    case "work":
      return e.task ?? s.working;
    case "meeting": {
      const partner = e.meeting_with ? staff[e.meeting_with] : undefined;
      return partner ? s.meetingWith(partner.name) : s.meeting;
    }
    case "coffee":
      return s.coffee;
    case "walk":
      return s.resting;
    case "off":
      return s.off;
    default:
      return e.is_coordinator ? s.inRoom : s.resting;
  }
}

/** A line for the office feed when an employee's state changes (null: nothing to say). */
export function feedLine(before: OfficeEmployee | undefined, after: EmployeeState, staff: Staff): string | null {
  const f = tr.office.feed;
  if (after.needs_user && !before?.needs_user) return after.needs_user_reason === "budget" ? f.budget : f.waiting;
  if (after.activity === "meeting" && before?.activity !== "meeting") {
    const partner = after.meeting_with ? staff[after.meeting_with]?.name : undefined;
    return partner ? f.meeting(partner, after.task) : f.meetingAlone;
  }
  if (after.activity === "working" && after.task && after.task !== before?.task && !after.tool) return f.started(after.task);
  if (after.activity === "break" && (before?.activity === "working" || before?.activity === "meeting")) return f.done;
  return null;
}

/** Hair and skin for a figure: stable per employee (the prototype's palette). */
const HAIR = ["#3a2a1e", "#1f1b2e", "#2b1d14", "#43232f", "#2a1a3a", "#5a3a22", "#251a12", "#2e2a26", "#1c1c1c", "#2a2140"];
const HEAD = ["#e8c29d", "#c99a74", "#f2d0b0", "#e6b892", "#f3d6bd", "#edc7a3", "#d9a882", "#e3b98f", "#c48f66", "#f0d2b4"];

export function looks(id: string): { hair: string; head: string } {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return { hair: HAIR[h % HAIR.length] ?? "#2a2140", head: HEAD[(h >>> 4) % HEAD.length] ?? "#e8c29d" };
}
