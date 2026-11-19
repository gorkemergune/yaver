import { describe, expect, it } from "vitest";

import type { Change } from "../api/types";
import { describeChange, visibleChanges } from "./changes";

function change(entity: string, data: Change["data"], op: Change["op"] = "create"): Change {
  return { entity, op, agent_id: "academic", data, undone: false };
}

describe("describeChange", () => {
  it("weekly block", () => {
    expect(
      describeChange(
        change("recurring_blocks", {
          title: "Linear Algebra",
          kind: "class",
          weekday: 0,
          start_time: "09:00:00",
          end_time: "11:00:00",
        }),
      ),
    ).toBe("Haftalık ders: Linear Algebra (Pzt 09:00–11:00) eklendi");
  });

  it("cancelled occurrence", () => {
    expect(
      describeChange(change("block_overrides", { title: "Spor", action: "cancel", date: "2026-11-24" })),
    ).toMatch(/^Spor .*24.* iptal edildi$/);
  });

  it("attendance", () => {
    expect(
      describeChange(change("attendance", { course: "EE211", date: "2026-11-17", status: "absent" })),
    ).toMatch(/^EE211 .*17.*: devamsızlık kaydedildi$/);
  });

  it("unknown entity falls back to the table name", () => {
    expect(describeChange(change("llm_usage", {}, "delete"))).toBe("llm_usage silindi");
  });
});

describe("visibleChanges", () => {
  it("hides courses created together with their blocks", () => {
    const changes = [change("courses", { code: "EE211" }), change("recurring_blocks", { title: "EE211 Lab" })];
    expect(visibleChanges(changes).map((c) => c.entity)).toEqual(["recurring_blocks"]);
  });

  it("keeps course changes on their own", () => {
    const limit = change("courses", { code: "EE211", absence_limit: 4 }, "update");
    expect(visibleChanges([limit])).toEqual([limit]);
  });
});
