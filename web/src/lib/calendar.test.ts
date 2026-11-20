import { describe, expect, it } from "vitest";

import { subscriptionUrls } from "./calendar";

describe("subscriptionUrls", () => {
  it("turns the page origin into webcal://", () => {
    const urls = subscriptionUrls("https://pc.tail1234.ts.net", "/api/calendar.ics?token=abc");
    expect(urls.webcal).toBe("webcal://pc.tail1234.ts.net/api/calendar.ics?token=abc");
    expect(urls.https).toBe("https://pc.tail1234.ts.net/api/calendar.ics?token=abc");
    expect(subscriptionUrls("http://localhost:8080", "/x").webcal).toBe("webcal://localhost:8080/x");
  });
});
