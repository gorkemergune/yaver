import { describe, expect, it } from "vitest";

import type { EmployeeState, OfficeEmployee, OfficeEvent } from "../api/types";
import { SPOTS, inMeetingRoom, need } from "./geometry";
import { applyOfficeEvent, feedLine, figureView, planFigures, stepFigures, type Figure, type Staff } from "./model";

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

/** Walk every figure until it arrives. */
function arrive(figures: Record<string, Figure>): Record<string, Figure> {
  let current = figures;
  for (let i = 0; i < 200; i++) current = stepFigures(current);
  return current;
}

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
