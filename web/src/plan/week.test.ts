import { describe, expect, it } from "vitest";

import { mondayOf, movedTo, shiftWeek, swipeDirection, weekParam, weekRange } from "./week";

describe("week helpers", () => {
  it("finds the Monday and moves by weeks", () => {
    expect(mondayOf("2026-11-20")).toBe("2026-11-16");
    expect(mondayOf("2026-11-22")).toBe("2026-11-16"); // Sunday
    expect(mondayOf("2026-11-16")).toBe("2026-11-16");
    expect(shiftWeek("2026-11-16", 1)).toBe("2026-11-23");
    expect(shiftWeek("2026-11-16", -3)).toBe("2026-10-26");
    expect(shiftWeek("2026-12-28", 1)).toBe("2027-01-04");
  });

  it("reads ?week= safely", () => {
    expect(weekParam("2026-11-18")).toBe("2026-11-16");
    expect(weekParam(null)).toBeNull();
    expect(weekParam("geçen hafta")).toBeNull();
    expect(weekParam("2026-13-45")).toBeNull();
  });

  it("names the range", () => {
    expect(weekRange("2026-11-16")).toBe("16–22 Kasım");
    expect(weekRange("2026-11-30")).toBe("30 Kasım – 6 Aralık");
    expect(weekRange("2026-12-28")).toBe("28 Aralık 2026 – 3 Ocak 2027");
  });

  it("says where a moved class went", () => {
    expect(movedTo("2026-11-20 14:00", "2026-11-18")).toBe("Cum 20 Kas 14:00");
    expect(movedTo("2026-11-18 14:00", "2026-11-18")).toBe("14:00");
  });

  it("tells a swipe from a scroll", () => {
    expect(swipeDirection(120, 10)).toBe(-1);
    expect(swipeDirection(-120, 10)).toBe(1);
    expect(swipeDirection(-120, 200)).toBe(0); // mostly vertical: a scroll
    expect(swipeDirection(30, 0)).toBe(0);
  });
});
