import { describe, expect, it } from "vitest";
import { isDrag } from "./drag";

describe("isDrag", () => {
  it("treats a tiny wobble as a click", () => {
    expect(isDrag({ x: 10, y: 10 }, { x: 12, y: 11 })).toBe(false);
  });

  it("treats real movement as a drag", () => {
    expect(isDrag({ x: 10, y: 10 }, { x: 16, y: 10 })).toBe(true);
  });
});
