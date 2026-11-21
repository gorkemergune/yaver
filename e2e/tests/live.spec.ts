import { expect, test, type Page, type Response } from "@playwright/test";

import { lit, scalar, spentUsd } from "../helpers/db";
import { ANSWER_TIMEOUT_MS, LIVE_BUDGET_USD } from "../helpers/env";
import { tag } from "../helpers/seed";

/**
 * Real LLM calls (LIVE=1 npm run test:live). Groq answers first; Claude is the failover and is
 * capped by CLAUDE_MONTHLY_BUDGET_USD=0.30 in the e2e stack. Every test is skipped once the
 * e2e database has recorded LIVE_BUDGET_USD of spend, and the suite fails if it went over.
 */

const typing = (page: Page) => page.getByRole("status", { name: "yazıyor" });
const ERROR_TEXT = /Sunucuya ulaşılamadı|Bir şeyler ters gitti|yanıt veremedi/;

test.describe("live chat @live", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(() => {
    const spent = spentUsd();
    test.skip(spent >= LIVE_BUDGET_USD - 0.02, `live budget used up: $${spent.toFixed(4)}`);
  });

  test.afterAll(() => {
    const spent = spentUsd();
    console.log(`e2e live spend so far: $${spent.toFixed(4)}`);
    expect(spent).toBeLessThanOrEqual(LIVE_BUDGET_USD);
  });

  async function streamDone(response: Response): Promise<Record<string, unknown>> {
    const body = await response.text();
    const events = body
      .split("\n\n")
      .filter((b) => b.startsWith("data: "))
      .map((b) => JSON.parse(b.slice(6)) as Record<string, unknown>);
    const last = events[events.length - 1];
    expect(last?.type, `last event: ${JSON.stringify(last)}`).toBe("done");
    return last as Record<string, unknown>;
  }

  test("a chat message gets an answer within 60 s @live", async ({ page }) => {
    await page.route("**/api/conversations/latest", (route) => route.fulfill({ json: { conversation_id: null } }));
    await page.goto("/#/chat");
    const started = Date.now();
    const response = page.waitForResponse((r) => r.url().endsWith("/api/chat/stream"), { timeout: ANSWER_TIMEOUT_MS });
    await page.getByPlaceholder("Yaver'e yaz…").fill("Merhaba! Tek kısa cümleyle ne yapabildiğini söyler misin?");
    await page.getByRole("button", { name: "Gönder" }).click();
    const done = await streamDone(await response);
    await expect(typing(page)).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });
    expect(Date.now() - started).toBeLessThan(ANSWER_TIMEOUT_MS);
    await expect(page.getByText(ERROR_TEXT)).toHaveCount(0);
    const reply = String(done.reply ?? "");
    expect(reply.length).toBeGreaterThan(0);
    await expect(page.getByText(reply.slice(0, 30), { exact: false }).first()).toBeVisible();
  });

  test("an event added through the chat can be undone with Geri al @live", async ({ page }) => {
    const title = tag("E2E canli toplanti");
    await page.route("**/api/conversations/latest", (route) => route.fulfill({ json: { conversation_id: null } }));
    await page.goto("/#/chat");
    const response = page.waitForResponse((r) => r.url().endsWith("/api/chat/stream"), { timeout: ANSWER_TIMEOUT_MS });
    await page
      .getByPlaceholder("Yaver'e yaz…")
      .fill(`Yarın saat 16:00 ile 17:00 arasına "${title}" başlıklı bir toplantı ekle.`);
    await page.getByRole("button", { name: "Gönder" }).click();
    const done = await streamDone(await response);
    await expect(typing(page)).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });
    expect(done.change_set_id, `reply: ${String(done.reply)}`).toBeTruthy();
    expect(scalar(`SELECT count(*) FROM events WHERE title = ${lit(title)};`)).toBe("1");

    await page.getByRole("button", { name: "Geri al" }).click();
    await expect(page.getByText("Geri alındı")).toBeVisible();
    expect(scalar(`SELECT count(*) FROM events WHERE title = ${lit(title)};`)).toBe("0");
  });

  test("direct chat with an employee answers within 60 s @live", async ({ page }) => {
    await page.goto("/#/office?employee=agenda");
    const panel = page.getByRole("region", { name: "Chrono" });
    const response = page.waitForResponse((r) => /\/api\/employees\/agenda\/chat\/stream$/.test(r.url()), {
      timeout: ANSWER_TIMEOUT_MS,
    });
    await panel.getByPlaceholder("Chrono: soru yaz…").fill("Yarın takvimimde ne var? Kısaca söyle.");
    await panel.getByRole("button", { name: "Sor" }).click();
    const done = await streamDone(await response);
    await expect(panel.getByRole("status", { name: "yazıyor" })).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });
    await expect(panel.getByText(ERROR_TEXT)).toHaveCount(0);
    expect(String(done.reply ?? "").length).toBeGreaterThan(0);
    // the inbox records the direct task
    await expect(panel.getByText("Yarın takvimimde ne var? Kısaca söyle.").first()).toBeVisible();
  });
});
