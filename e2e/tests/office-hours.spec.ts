import { expect, test, type Page } from "@playwright/test";

/**
 * O5: outside office hours. The real snapshot with the office closed and one employee on a
 * night shift, served to the page (snapshot + stream) so it does not depend on the clock:
 * empty dark desks, the night-shift worker at its lit desk, the zoomed desk screen, the
 * sound switch (off by default, remembered).
 */
interface Employee {
  id: string;
  name: string;
  activity: string;
  task: string | null;
  tool: string | null;
  desk: { row: string; col: number };
  [key: string]: unknown;
}
interface Snapshot {
  ready: boolean;
  employees: Employee[];
  hours: { open_at: string; close_at: string; off_hours: boolean };
  ts: string;
}

const TASK = "Toplantı ekliyor";

async function serveNight(page: Page, real: Snapshot): Promise<Snapshot> {
  const night: Snapshot = {
    ...real,
    hours: { open_at: "08:00", close_at: "23:00", off_hours: true },
    employees: real.employees.map((e) =>
      e.id === "agenda"
        ? { ...e, activity: "working", task: TASK, tool: "add_event", since: new Date().toISOString() }
        : { ...e, activity: "off", task: null, tool: null },
    ),
  };
  await page.route("**/api/office/snapshot", (route) => route.fulfill({ json: night }));
  await page.route("**/api/office/stream", (route) =>
    route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
      body: `retry: 3000\n\ndata: ${JSON.stringify({ type: "snapshot", ...night })}\n\n`,
    }),
  );
  return night;
}

test("night: desks are dark, a request is a night shift, a desk zooms into its screen", async ({ page, request }) => {
  const real = (await (await request.get("/api/office/snapshot")).json()) as Snapshot;
  expect(real.hours.open_at).toMatch(/^\d\d:\d\d$/); // the backend sends office hours
  const night = await serveNight(page, real);
  const chrono = night.employees.find((e) => e.id === "agenda");
  const scholar = night.employees.find((e) => e.id === "academic");
  test.skip(!chrono || !scholar, "the team has no agenda / academic employee");

  await page.goto("/#/office");
  await expect(page.getByText("Mesai dışı · açılış 08:00")).toBeVisible();
  await expect(page.locator('[data-desk="academic"]')).toHaveAttribute("data-state", "dark");
  await expect(page.locator('[data-desk="agenda"]')).toHaveAttribute("data-state", "lit");
  await expect(page.locator('[data-employee="agenda"]')).toBeVisible();
  await expect(page.locator('[data-employee="academic"]')).toHaveCount(0); // gone home
  const list = page.getByRole("list", { name: "Çalışan durumları" });
  await expect(list.getByRole("button", { name: `${chrono!.name}, ${String(chrono!.role)} — Gece mesaisi: ${TASK}` })).toBeVisible();
  await page.screenshot({ path: "test-results/office-night.png" });

  await page.locator('[data-desk="agenda"]').click();
  const screen = page.getByRole("dialog", { name: `${chrono!.name} ekranı` });
  await expect(screen).toBeVisible();
  await expect(screen.getByText(`Gece mesaisi: ${TASK}`)).toBeVisible();
  await expect(screen.getByText("Araç: add_event", { exact: false })).toBeVisible();
  // the zoom animation done (the screenshot shows the screen, not a frame of the zoom)
  await screen.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
  await page.screenshot({ path: "test-results/office-screen.png" });
  await page.keyboard.press("Escape");
  await expect(screen).toBeHidden();

  // a back-row desk: its upper part (the front row's monitors cover its front edge)
  const back = page.locator('[data-desk="academic"]');
  const box = await back.boundingBox();
  await back.click({ position: { x: (box?.width ?? 40) / 2, y: 10 } });
  const dark = page.getByRole("dialog", { name: `${scholar!.name} ekranı` });
  await expect(dark.getByText("Ekran kapalı · mesai dışı")).toBeVisible();
  await dark.getByRole("button", { name: "Ekranı kapat" }).click();
  await expect(dark).toBeHidden();
});

test("sound effects are off by default and the choice is remembered", async ({ page }) => {
  await page.goto("/#/office");
  const sound = page.getByRole("button", { name: "Ses efektleri" });
  await expect(sound).toHaveAttribute("aria-pressed", "false");
  await sound.click();
  await expect(sound).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByRole("button", { name: "Ses efektleri" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Ses efektleri" }).click();
  await expect(page.getByRole("button", { name: "Ses efektleri" })).toHaveAttribute("aria-pressed", "false");
});
