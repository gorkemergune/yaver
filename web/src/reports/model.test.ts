import { describe, expect, it } from "vitest";

import { shiftDate } from "./model";

describe("shiftDate", () => {
  it("moves by days across months and years, in local dates", () => {
    expect(shiftDate("2026-11-22", 1)).toBe("2026-11-23");
    expect(shiftDate("2026-11-30", 1)).toBe("2026-12-01");
    expect(shiftDate("2026-01-01", -1)).toBe("2025-12-31");
    expect(shiftDate("2026-11-22", -7)).toBe("2026-11-15");
  });
});
