import { describe, expect, it } from "vitest";

import type { PlanItem } from "../api/types";
import { detailLines, timeRange } from "./details";

const base: PlanItem = { type: "event", id: 1, kind: "exam", title: "EE211 (Devre Analizi) Ara Sınav" };

describe("timeRange", () => {
  it("start-end, a point in time, all day", () => {
    expect(timeRange({ ...base, start: "09:00", end: "11:00" })).toBe("09:00–11:00");
    expect(timeRange({ ...base, start: "14:00" })).toBe("14:00");
    expect(timeRange({ ...base, all_day: true })).toBe("Tüm gün");
  });

  it("shows the days of an item that runs past midnight", () => {
    const range = timeRange({ ...base, start: "23:00", end: "02:00", starts_on: "2026-11-27", ends_on: "2026-11-28" });

    expect(range).toMatch(/^27 Kas .* 23:00 – 28 Kas .* 02:00$/);
  });
});

describe("detailLines", () => {
  it("lists everything an opened card shows, in order", () => {
    const lines = detailLines({
      ...base,
      start: "10:00",
      end: "12:00",
      location: "B201 ve B202",
      note: "Okul otobüsü ile kampüse 9:15'te çıkılıyor, kimlik kartı unutma",
    });

    expect(lines.map((line) => line.label)).toEqual(["Saat", "Tür", "Yer", "Not"]);
    expect(lines[0]?.value).toBe("10:00–12:00");
    expect(lines[3]?.value).toContain("kimlik kartı unutma"); // the note is shown in full
  });

  it("leaves out what the item does not have", () => {
    expect(detailLines({ ...base, start: "10:00" }).map((line) => line.label)).toEqual(["Saat", "Tür"]);
  });
});
