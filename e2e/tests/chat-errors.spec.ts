import { expect, test, type Page, type Route } from "@playwright/test";

import { ANSWER_TIMEOUT_MS } from "../helpers/env";

/**
 * The chat must never sit on "yazıyor…" forever: whatever goes wrong between the browser and
 * the model, the answer bubble ends with a visible error and the composer is usable again.
 * The failures are injected at the network layer (no LLM calls, no money).
 */

const sse = (...events: object[]): string => events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
const typing = (page: Page) => page.getByRole("status", { name: "yazıyor" });
const ERRORS = {
  network: "Sunucuya ulaşılamadı.",
  llm: "Şu an hiçbir model yanıt veremedi",
  internal: "Bir şeyler ters gitti; hiçbir değişiklik kaydedilmedi.",
};

async function openEmptyChat(page: Page): Promise<void> {
  // start without history so the only answer on screen is the one under test
  await page.route("**/api/conversations/latest", (route) => route.fulfill({ json: { conversation_id: null } }));
  await page.goto("/#/chat");
  await expect(page.getByPlaceholder("Yaver'e yaz…")).toBeEnabled();
}

async function send(page: Page, text: string): Promise<void> {
  await page.getByPlaceholder("Yaver'e yaz…").fill(text);
  await page.getByRole("button", { name: "Gönder" }).click();
  await expect(page.getByText(text)).toBeVisible();
}

async function expectSettled(page: Page, error: string | RegExp, timeout = 15_000): Promise<void> {
  await expect(page.getByText(error)).toBeVisible({ timeout });
  await expect(typing(page)).toHaveCount(0);
  await expect(page.getByPlaceholder("Yaver'e yaz…")).toBeEnabled();
}

test.describe("chat error handling (mocked network)", () => {
  test("HTTP 500 from /api/chat/stream shows an error", async ({ page }) => {
    await openEmptyChat(page);
    await page.route("**/api/chat/stream", (route) => route.fulfill({ status: 500, body: "Internal Server Error" }));
    await send(page, "e2e 500 testi");
    await expectSettled(page, ERRORS.network);
  });

  test("network failure (connection refused) shows an error", async ({ page }) => {
    await openEmptyChat(page);
    await page.route("**/api/chat/stream", (route) => route.abort("connectionrefused"));
    await send(page, "e2e bağlantı testi");
    await expectSettled(page, ERRORS.network);
  });

  test("SSE error llm_unavailable shows the quota message", async ({ page }) => {
    await openEmptyChat(page);
    await page.route("**/api/chat/stream", (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: sse({ type: "turn", agent_id: "yaver" }, { type: "error", code: "llm_unavailable" }),
      }),
    );
    await send(page, "e2e kota testi");
    await expectSettled(page, ERRORS.llm);
  });

  test("SSE error internal shows the generic message", async ({ page }) => {
    await openEmptyChat(page);
    await page.route("**/api/chat/stream", (route) =>
      route.fulfill({
        contentType: "text/event-stream",
        body: sse({ type: "turn", agent_id: "yaver" }, { type: "error", code: "internal" }),
      }),
    );
    await send(page, "e2e iç hata testi");
    await expectSettled(page, ERRORS.internal);
  });

  test("a stream that closes without done/error does not leave a silent empty answer", async ({ page }) => {
    await openEmptyChat(page);
    // e.g. the API process restarted (uvicorn --reload) or a proxy cut the response
    await page.route("**/api/chat/stream", (route) =>
      route.fulfill({ contentType: "text/event-stream", body: sse({ type: "turn", agent_id: "yaver" }) }),
    );
    await send(page, "e2e yarım akış testi");
    await expectSettled(page, /Sunucuya ulaşılamadı|Bir şeyler ters gitti|yanıt veremedi/);
  });

  test("a stream that never answers ends with an error, not endless 'yazıyor…'", async ({ page }) => {
    test.setTimeout(ANSWER_TIMEOUT_MS + 60_000);
    await openEmptyChat(page);
    // the server accepts the request and then never sends a byte (hung LLM call, deadlock,
    // an exception swallowed before `done`/`error`)
    const held: Route[] = [];
    await page.route("**/api/chat/stream", (route) => {
      held.push(route);
    });
    await send(page, "e2e asılı kalma testi");
    await expect(typing(page)).toBeVisible();
    try {
      await expectSettled(page, /Sunucuya ulaşılamadı|Bir şeyler ters gitti|yanıt veremedi|zaman aşımı|cevap gelmedi/i, ANSWER_TIMEOUT_MS + 20_000);
    } finally {
      for (const route of held) await route.abort().catch(() => undefined);
    }
  });

  test("the office composer shows the same errors (Son cevap)", async ({ page }) => {
    await page.route("**/api/conversations/latest", (route) => route.fulfill({ json: { conversation_id: null } }));
    await page.route("**/api/chat/stream", (route) => route.fulfill({ status: 502, body: "Bad Gateway" }));
    await page.goto("/#/office");
    await page.getByPlaceholder("Yaver'e yaz…").fill("e2e ofis 502 testi");
    await page.getByRole("button", { name: "Gönder" }).click();
    const last = page.getByRole("region", { name: "Son cevap" });
    await expect(last.getByText(ERRORS.network)).toBeVisible();
    await expect(typing(page)).toHaveCount(0);
  });

  test("direct chat with an employee shows an error on HTTP 500", async ({ page }) => {
    await page.route("**/api/employees/*/chat/stream", (route) => route.fulfill({ status: 500, body: "boom" }));
    await page.goto("/#/office?employee=agenda");
    const panel = page.getByRole("region", { name: "Chrono" });
    await panel.getByPlaceholder("Chrono: soru yaz…").fill("e2e doğrudan sohbet hatası");
    await panel.getByRole("button", { name: "Sor" }).click();
    await expect(panel.getByText(ERRORS.network)).toBeVisible();
    await expect(panel.getByRole("status", { name: "yazıyor" })).toHaveCount(0);
  });
});
