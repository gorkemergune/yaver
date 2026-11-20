import { describe, expect, it } from "vitest";

import type { EmployeeState, OfficeEmployee, OfficeEvent } from "../api/types";
import { SPOTS, inMeetingRoom, need } from "./geometry";
import { DWELL_MS, applyOfficeEvent, feedLine, figureView, meetingSeats, planFigures, stepFigures, type Figure, type Staff } from "./model";

function employee(id: string, desk: OfficeEmployee["desk"], extra: Partial<OfficeEmployee> = {}): OfficeEmployee {
  return {
    id,
    employee_id: id,
    name: id === "yaver" ? "Yaver" : id === "academic" ? "Atlas" : id === "agenda" ? "Deniz" : "Kaan",
    role: "",
    color: "#4cbcff",
    desk,
    is_coordinator: id === "yaver",
    domain: "",
    shift: "",
    daily_budget_usd: 0.5,
    spent_today_usd: 0,
    activity: "break",
    task: null,
    tool: null,
    meeting_with: null,
    needs_user: false,
    needs_user_reason: null,
    since: "2026-11-21T10:00:00+00:00",
    ts: "2026-11-21T10:00:00+00:00",
    ...extra,
  };
}

const STAFF: Staff = {
  yaver: employee("yaver", { row: "office", col: 0 }),
  academic: employee("academic", { row: "back", col: 0 }),
  agenda: employee("agenda", { row: "front", col: 2 }),
  discipline: employee("discipline", { row: "front", col: 3 }),
};

function state(id: string, patch: Partial<EmployeeState>): OfficeEvent {
  return {
    type: "state",
    employee_id: id,
    activity: "break",
    task: null,
    tool: null,
    meeting_with: null,
    needs_user: false,
    needs_user_reason: null,
    since: "2026-11-21T10:00:00+00:00",
    ts: "2026-11-21T10:00:01+00:00",
    ...patch,
  };
}

/** A deterministic random: always the same pick. */
const fixed = (value: number) => () => value;

/** Walk every figure until it arrives (arrival at `at` ms). */
function arrive(figures: Record<string, Figure>, at = 0): Record<string, Figure> {
  let current = figures;
  for (let i = 0; i < 200; i++) current = stepFigures(current, at);
  return current;
}

const TICK = 900;

describe("applyOfficeEvent", () => {
  it("a snapshot replaces everyone; not ready means an empty office", () => {
    const snapshot: OfficeEvent = { type: "snapshot", ready: true, employees: Object.values(STAFF), ts: "" };
    expect(Object.keys(applyOfficeEvent({}, snapshot))).toEqual(["yaver", "academic", "agenda", "discipline"]);
    expect(applyOfficeEvent(STAFF, { type: "snapshot", ready: false, employees: [], ts: "" })).toEqual({});
  });

  it("a state event updates one employee and keeps its desk and name", () => {
    const next = applyOfficeEvent(STAFF, state("academic", { activity: "working", task: "Takvime bakıyor", tool: "get_day_plan" }));
    expect(next.academic).toMatchObject({ name: "Atlas", desk: { row: "back", col: 0 }, activity: "working", task: "Takvime bakıyor" });
    expect(next.agenda).toBe(STAFF.agenda);
    expect(next.academic).not.toHaveProperty("type");
  });

  it("unknown employees and notes leave the staff as is", () => {
    expect(applyOfficeEvent(STAFF, state("nobody", { activity: "working" }))).toBe(STAFF);
    const note: OfficeEvent = { type: "note", employee_id: "academic", note: { id: 1, content: "x", created_at: null }, ts: "" };
    expect(applyOfficeEvent(STAFF, note)).toBe(STAFF);
    expect(applyOfficeEvent(STAFF, { type: "ping", ts: "" })).toBe(STAFF);
  });
});

describe("figures follow the backend state", () => {
  it("working: walks to its own desk and sits with the bubble", () => {
    const idle = planFigures({}, STAFF, 0, fixed(0.1)); // academic starts at the coffee corner
    expect(idle.academic?.act).toBe("coffee");
    const working = applyOfficeEvent(STAFF, state("academic", { activity: "working", task: "Haftalık programa ekliyor" }));
    const walking = planFigures(idle, working, 1000);
    expect(walking.academic?.spot).toBe("seat:back:0");
    expect(walking.academic?.path.length).toBeGreaterThan(0);
    const mid = figureView(need(walking.academic, "academic"), need(working.academic, "academic"), working);
    expect(mid).toMatchObject({ walking: true, atDesk: false, sitting: false, status: "Masasına dönüyor" });
    expect(mid.hasCup).toBe(true); // carries the coffee back

    // the next ticks follow the same route (no new route while the target stays)
    const replanned = planFigures(stepFigures(walking, 1900), working, 2000);
    expect(replanned.academic?.path).toEqual(walking.academic?.path.slice(1));

    const seated = arrive(walking);
    expect([seated.academic?.x, seated.academic?.y]).toEqual(SPOTS["seat:back:0"]?.pt);
    const view = figureView(need(seated.academic, "academic"), need(working.academic, "academic"), working);
    expect(view).toMatchObject({ walking: false, atDesk: true, sitting: true, fromBehind: false, hasCup: false });
    expect(view.status).toBe("Haftalık programa ekliyor");
  });

  it("front row desks are seen from behind", () => {
    const working = applyOfficeEvent(STAFF, state("discipline", { activity: "working" }));
    const figures = planFigures({}, working, 0);
    const view = figureView(need(figures.discipline, "discipline"), need(working.discipline, "discipline"), working);
    expect(figures.discipline?.spot).toBe("seat:front:3");
    expect(view).toMatchObject({ sitting: true, fromBehind: true, atDesk: true });
  });

  it("meeting: both sides of a delegation sit across the same table", () => {
    let staff = applyOfficeEvent(STAFF, state("yaver", { activity: "meeting", meeting_with: "academic", task: "EE211 ekle" }));
    staff = applyOfficeEvent(staff, state("academic", { activity: "meeting", meeting_with: "yaver", task: "EE211 ekle" }));
    const figures = arrive(planFigures(planFigures({}, STAFF, 0), staff, 1000));

    expect(figures.yaver?.spot).toBe("meet:0"); // near side, facing us
    expect(figures.academic?.spot).toBe("meet:3"); // across
    for (const id of ["yaver", "academic"]) {
      const f = need(figures[id], id);
      expect(inMeetingRoom(f.x, f.y)).toBe(true);
    }
    expect(figureView(need(figures.academic, "academic"), need(staff.academic, "academic"), staff).status).toBe("Yaver ile toplantıda");

    // a second pair takes the next table seats; the first pair stays where it is
    staff = applyOfficeEvent(staff, state("agenda", { activity: "meeting", meeting_with: "discipline" }));
    staff = applyOfficeEvent(staff, state("discipline", { activity: "meeting", meeting_with: "agenda" }));
    const more = planFigures(figures, staff, 2000);
    expect([more.yaver?.spot, more.academic?.spot]).toEqual(["meet:0", "meet:3"]);
    expect([more.agenda?.spot, more.discipline?.spot]).toEqual(["meet:1", "meet:4"]);
  });

  it("meeting ends with the first tool: the employee goes to its desk, Yaver to its room", () => {
    let staff = applyOfficeEvent(STAFF, state("yaver", { activity: "meeting", meeting_with: "academic" }));
    staff = applyOfficeEvent(staff, state("academic", { activity: "meeting", meeting_with: "yaver" }));
    const met = arrive(planFigures({}, staff, 0));
    staff = applyOfficeEvent(staff, state("academic", { activity: "working", tool: "add_note", task: "Defterine yazıyor" }));
    staff = applyOfficeEvent(staff, state("yaver", { activity: "working", task: "Atlas çalışıyor, bekliyor" }));
    const after = planFigures(met, staff, 1000);
    expect(after.academic?.spot).toBe("seat:back:0");
    expect(after.yaver?.spot).toBe("seat:office");
    expect(after.yaver?.path.length).toBeGreaterThan(0); // walks back out of the meeting room
  });

  it("a meeting shorter than the walk is still shown, then the figure follows the latest state", () => {
    let staff = applyOfficeEvent(STAFF, state("yaver", { activity: "meeting", meeting_with: "agenda" }));
    staff = applyOfficeEvent(staff, state("agenda", { activity: "meeting", meeting_with: "yaver" }));
    let figures = planFigures(planFigures({}, STAFF, 0, fixed(0.1)), staff, 0, fixed(0.1));
    const seat = figures.agenda?.spot;
    expect(seat).toMatch(/^meet:/);

    // ~1 s later the backend handover is over: Deniz works, Yaver waits in its room
    staff = applyOfficeEvent(staff, state("agenda", { activity: "working", task: "Takvime ekliyor", tool: "add_event" }));
    staff = applyOfficeEvent(staff, state("yaver", { activity: "working", task: "Deniz çalışıyor, bekliyor" }));
    let t = 0;
    while ((figures.agenda?.path.length ?? 0) > 0) {
      t += TICK;
      figures = stepFigures(planFigures(figures, staff, t), t);
      expect(figures.agenda?.spot).toBe(seat); // keeps walking to the meeting
    }
    expect(inMeetingRoom(need(figures.agenda, "agenda").x, need(figures.agenda, "agenda").y)).toBe(true);
    // sits it out...
    figures = planFigures(figures, staff, t + (DWELL_MS.meeting ?? 0) - 100);
    expect(figures.agenda?.spot).toBe(seat);
    // ...then goes to its desk to do the work the backend reported
    figures = planFigures(figures, staff, t + (DWELL_MS.meeting ?? 0) + 100);
    expect(figures.agenda?.spot).toBe("seat:front:2");
    expect(figures.agenda?.act).toBe("work");
  });

  it("a meeting cuts a walk to the desk short", () => {
    const working = applyOfficeEvent(STAFF, state("academic", { activity: "working" }));
    const walking = planFigures(planFigures({}, STAFF, 0, fixed(0.1)), working, 0);
    expect(walking.academic?.path.length).toBeGreaterThan(0);
    const meeting = applyOfficeEvent(working, state("academic", { activity: "meeting", meeting_with: "yaver" }));
    expect(planFigures(walking, meeting, TICK).academic?.spot).toMatch(/^meet:/);
  });

  it("the next meeting partner sits across from someone still in the room", () => {
    // Yaver is still sitting out its meeting with Deniz at meet:0 / meet:3
    const figures: Record<string, Figure> = {
      yaver: { id: "yaver", spot: "meet:0", act: "meeting", x: 1.21, y: 6.24, path: [], cup: false, idleUntil: 0, holdUntil: 5000 },
      agenda: { id: "agenda", spot: "meet:3", act: "meeting", x: 1.03, y: 8.19, path: [], cup: false, idleUntil: 0, holdUntil: 5000 },
    };
    let staff = applyOfficeEvent(STAFF, state("yaver", { activity: "meeting", meeting_with: "academic" }));
    staff = applyOfficeEvent(staff, state("academic", { activity: "meeting", meeting_with: "yaver" }));
    const seats = meetingSeats(staff, figures, 1000);
    expect(seats.yaver).toBe("meet:0");
    expect(seats.agenda).toBe("meet:3");
    expect(seats.academic).toBe("meet:4"); // across from Yaver's side, next to Deniz
  });

  it("standup: ten people fit in the meeting room, everyone on a different spot", () => {
    const ids = ["yaver", "academic", "agenda", "discipline", "career", "startup", "ads", "research", "content", "social"];
    const staff: Staff = Object.fromEntries(
      ids.map((id, i) => [
        id,
        employee(id, id === "yaver" ? { row: "office", col: 0 } : { row: i % 2 ? "back" : "front", col: i % 5 }, {
          activity: "meeting",
          meeting_with: id === "yaver" ? null : "yaver",
        }),
      ]),
    );
    const figures = arrive(planFigures({}, staff, 0));
    const spots = Object.values(figures).map((f) => f.spot);
    expect(new Set(spots).size).toBe(10);
    for (const f of Object.values(figures)) {
      expect(f.spot).toMatch(/^meet:/);
      expect(inMeetingRoom(f.x, f.y)).toBe(true);
    }
  });

  it("standup: nobody leaves before the last one arrives, then they stay together", () => {
    const ids = ["yaver", "academic", "agenda"];
    const desks: Record<string, OfficeEmployee["desk"]> = { yaver: { row: "office", col: 0 }, academic: { row: "back", col: 0 }, agenda: { row: "front", col: 2 } };
    let staff: Staff = Object.fromEntries(
      ids.map((id) => [id, employee(id, desks[id] ?? { row: "back", col: 1 }, { activity: "meeting", meeting_with: id === "yaver" ? null : "yaver" })]),
    );
    let figures = planFigures(planFigures({}, STAFF, 0, fixed(0.1)), staff, 0, fixed(0.1));
    // the backend meeting is over at once (a few seconds of LLM calls)
    staff = Object.fromEntries(ids.map((id) => [id, { ...need(staff[id], id), activity: "break" as const, meeting_with: null }]));
    let t = 0;
    let lastArrival = 0;
    while (Object.values(figures).some((f) => f.path.length)) {
      t += TICK;
      const before = figures;
      figures = stepFigures(planFigures(figures, staff, t, fixed(0.1)), t);
      for (const f of Object.values(figures)) {
        if (need(before[f.id], f.id).path.length && !f.path.length) lastArrival = t;
        // while anyone walks in, those already there keep their seats
        expect(f.act).toBe("meeting");
      }
    }
    // after the last arrival everyone stays the full meeting time, then leaves
    const together = planFigures(figures, staff, lastArrival + (DWELL_MS.meeting ?? 0) - 100, fixed(0.1));
    expect(Object.values(together).every((f) => f.act === "meeting" && f.spot.startsWith("meet:"))).toBe(true);
    const after = planFigures(together, staff, lastArrival + (DWELL_MS.meeting ?? 0) + 100, fixed(0.1));
    expect(Object.values(after).some((f) => f.act !== "meeting")).toBe(true);
  });

  it("break: idle places only - never the meeting room or someone's desk", () => {
    for (const r of [0, 0.2, 0.5, 0.7, 0.99]) {
      const figures = planFigures({}, STAFF, 0, fixed(r));
      for (const f of Object.values(figures)) {
        expect(["coffee", "walk", "home"]).toContain(f.act);
        expect(f.spot.startsWith("meet:")).toBe(false);
        if (f.act === "home") expect(f.spot).toBe(f.id === "yaver" ? "seat:office" : `seat:${STAFF[f.id]?.desk.row ?? ""}:${String(STAFF[f.id]?.desk.col)}`);
      }
      const spots = Object.values(figures).map((f) => f.spot);
      expect(new Set(spots).size).toBe(spots.length); // nobody on top of another
    }
  });

  it("an idle figure keeps its place for a while, then may move on", () => {
    const first = planFigures({}, STAFF, 0, fixed(0.9));
    const soon = planFigures(first, STAFF, 5_000, fixed(0.1));
    expect(soon.academic?.spot).toBe(first.academic?.spot);
    const later = planFigures(soon, STAFF, 120_000, fixed(0.1));
    expect(later.academic?.idleUntil).toBeGreaterThan(120_000);
  });

  it("needs_user: red dot wherever it is, with the reason in the status", () => {
    const staff = applyOfficeEvent(STAFF, state("agenda", { needs_user: true, needs_user_reason: "question" }));
    const figures = planFigures({}, staff, 0);
    const view = figureView(need(figures.agenda, "agenda"), need(staff.agenda, "agenda"), staff);
    expect(view.alert).toBe(true);
    expect(view.status).toBe("Cevabını bekliyor");
    const budget = applyOfficeEvent(staff, state("agenda", { needs_user: true, needs_user_reason: "budget" }));
    expect(figureView(need(figures.agenda, "agenda"), need(budget.agenda, "agenda"), budget).status).toBe("Günlük bütçesi doldu");
  });

  it("figures of employees no longer in the office are dropped", () => {
    const figures = planFigures({}, STAFF, 0);
    const rest = Object.fromEntries(Object.entries(STAFF).filter(([id]) => id !== "discipline"));
    expect(Object.keys(planFigures(figures, rest, 1000))).toEqual(["yaver", "academic", "agenda"]);
  });
});

describe("feedLine", () => {
  it("says when work starts, a meeting begins, a job ends and the user is needed", () => {
    const yaver = need(STAFF.yaver, "yaver");
    const meeting = state("academic", { activity: "meeting", meeting_with: "yaver", task: "EE211 ekle" });
    if (meeting.type !== "state") throw new Error("state");
    expect(feedLine(STAFF.academic, meeting, STAFF)).toBe("Yaver ile toplantıda: EE211 ekle");
    const start = state("yaver", { activity: "working", task: "yarın ne var?" });
    if (start.type !== "state") throw new Error("state");
    expect(feedLine(yaver, start, STAFF)).toBe("işe başladı: yarın ne var?");
    const tool = state("yaver", { activity: "working", task: "Günün planına bakıyor", tool: "get_day_plan" });
    if (tool.type !== "state") throw new Error("state");
    expect(feedLine({ ...yaver, activity: "working", task: "yarın ne var?" }, tool, STAFF)).toBeNull(); // tool steps: too chatty
    const done = state("yaver", { activity: "break" });
    if (done.type !== "state") throw new Error("state");
    expect(feedLine({ ...yaver, activity: "working" }, done, STAFF)).toBe("işini bitirdi");
    const ask = state("agenda", { needs_user: true, needs_user_reason: "question" });
    if (ask.type !== "state") throw new Error("state");
    expect(feedLine(STAFF.agenda, ask, STAFF)).toBe("cevabını bekliyor");
  });
});
