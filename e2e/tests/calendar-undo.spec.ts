import { expect, test } from "@playwright/test";

import { eventExists, seedChangeSet, seedEvent, tag } from "../helpers/seed";

test.describe("calendar (Takvim)", () => {
  test("Bugün / Yarın / Hafta tabs show the plan, events land on the right local day", async ({ page }) => {
    const today = tag("E2E bugün etkinliği");
    const tomorrow = tag("E2E yarın etkinliği");
    seedEvent(today, 0, "20:00", "21:00");
    seedEvent(tomorrow, 1, "14:00", "15:00");

    await page.goto("/#/today");
    const tabs = page.getByRole("navigation", { name: "Takvim" });
    await expect(tabs.getByRole("link", { name: "Bugün" })).toHaveAttribute("aria-current", "page");
    await expect(page.getByText(today, { exact: true })).toBeVisible();
    await expect(page.getByText(tomorrow, { exact: true })).toHaveCount(0);

    await tabs.getByRole("link", { name: "Yarın" }).click();
    await expect(page).toHaveURL(/#\/tomorrow/);
    await expect(page.getByText(tomorrow, { exact: true })).toBeVisible();
    await expect(page.getByText(today, { exact: true })).toHaveCount(0);

    await tabs.getByRole("link", { name: "Hafta" }).click();
    await expect(page).toHaveURL(/#\/week/);
    await expect(page.getByRole("button", { name: "Önceki hafta" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Sonraki hafta" })).toBeVisible();
  });
});

test.describe("undo (Geri al)", () => {
  test("Geri al on an answer reverts its change set; a second undo is refused", async ({ page, request }) => {
    const title = tag("E2E geri al toplantısı");
    const seeded = seedChangeSet(title);
    expect(eventExists(seeded.eventId)).toBe(true);

    // the chat restores this conversation from localStorage
    await page.addInitScript((id) => {
      localStorage.setItem("yaver.conversation", String(id));
    }, seeded.conversationId);

    await page.goto("/#/tomorrow");
    await expect(page.getByText(title, { exact: true })).toBeVisible();

    await page.goto("/#/chat");
    await expect(page.getByText(`${title} yarın 10:00-11:00 olarak eklendi.`)).toBeVisible();
    const undo = page.getByRole("button", { name: "Geri al" });
    await expect(undo).toBeVisible();

    const call = page.waitForResponse((r) => r.url().includes(`/api/changes/${seeded.changeSetId}/undo`));
    await undo.click();
    expect((await call).status()).toBe(200);
    await expect(page.getByText("Geri alındı")).toBeVisible();
    expect(eventExists(seeded.eventId)).toBe(false);

    // after a reload the answer still reads "Geri alındı" (from the server, not local state)
    await page.reload();
    await expect(page.getByText("Geri alındı")).toBeVisible();
    await expect(page.getByRole("button", { name: "Geri al" })).toHaveCount(0);

    await page.goto("/#/tomorrow");
    await expect(page.getByText(title, { exact: true })).toHaveCount(0);

    const again = await request.post(`/api/changes/${seeded.changeSetId}/undo`);
    expect(again.status()).toBe(404);
  });
});
