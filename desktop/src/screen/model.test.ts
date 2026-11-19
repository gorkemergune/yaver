import { describe, expect, it } from "vitest";
import { fill, fmtDay, fmtDuration, limitState, topApps } from "./model";

describe("fmtDuration", () => {
  it("matches the Rust warning format", () => {
    expect(fmtDuration(30)).toBe("0 dk");
    expect(fmtDuration(300)).toBe("5 dk");
    expect(fmtDuration(3600)).toBe("1 sa");
    expect(fmtDuration(4320)).toBe("1 sa 12 dk");
    expect(fmtDuration(-1)).toBe("0 dk");
  });
});

describe("limitState", () => {
  it("turns at 80 % and 100 %", () => {
    expect(limitState(4319, 5400)).toBe("ok");
    expect(limitState(4320, 5400)).toBe("warn");
    expect(limitState(5400, 5400)).toBe("over");
    expect(limitState(10, 0)).toBe("ok");
  });
});

describe("fill", () => {
  it("is clamped to 0..1", () => {
    expect(fill(50, 100)).toBe(0.5);
    expect(fill(150, 100)).toBe(1);
    expect(fill(5, 0)).toBe(0);
  });
});

describe("topApps", () => {
  const apps = [5, 4, 3, 2, 1].map((s) => ({ exe: `${s}.exe`, name: `App ${s}`, seconds: s }));

  it("keeps short lists as they are", () => {
    expect(topApps(apps, 5, "Diğer")).toEqual(apps);
  });

  it("sums the tail into one row", () => {
    const top = topApps(apps, 3, "Diğer");
    expect(top.map((a) => a.name)).toEqual(["App 5", "App 4", "Diğer"]);
    expect(top[2]?.seconds).toBe(6);
  });
});

describe("fmtDay", () => {
  it("writes the date in Turkish", () => {
    expect(fmtDay("2026-11-20")).toBe("20 Kasım Cuma");
  });
});
