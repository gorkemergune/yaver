import { expect, test } from "@playwright/test";

import { seedEmployeeWork, tag } from "../helpers/seed";

interface Snapshot {
  ready: boolean;
  employees: { id: string; name: string }[];
}

test.describe("office", () => {
  test("loads, lists every employee and connects the SSE stream", async ({ page, request }) => {
    const snapshot = (await (await request.get("/api/office/snapshot")).json()) as Snapshot;
    expect(snapshot.ready).toBe(true);
    expect(snapshot.employees.length).toBeGreaterThan(0);

    const stream = page.waitForResponse((r) => r.url().endsWith("/api/office/stream"));
    await page.goto("/#/office");
    const response = await stream;
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("text/event-stream");

    await expect(page.getByRole("heading", { name: "Ofis", level: 1 })).toBeVisible();
    await expect(page.getByText("Ofis henüz hazır değil")).toHaveCount(0);
    // "N / M çalışan masasında" only shows once the EventSource reported open / a snapshot
    await expect(page.getByText(new RegExp(`/ ${String(snapshot.employees.length)} çalışan masasında`))).toBeVisible({
      timeout: 15_000,
    });

    const list = page.getByRole("list", { name: "Çalışan durumları" });
    for (const employee of snapshot.employees) {
      await expect(list.getByRole("button", { name: new RegExp(`^${employee.name},`) })).toBeVisible();
    }
  });

  test("the office stream sends a snapshot event first", async ({ page }) => {
    await page.goto("/#/office");
    // read the stream inside the browser (cookie auth) and return the first event
    const first = await page.evaluate(async () => {
      const controller = new AbortController();
      const res = await fetch("/api/office/stream", { signal: controller.signal });
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let text = "";
      while (!/^data: .*\n\n/m.test(text)) {
        const { value, done } = await reader.read();
        if (done) break;
        text += decoder.decode(value, { stream: true });
      }
      controller.abort();
      const block = text.split("\n\n").find((b) => b.startsWith("data: "));
      return JSON.parse((block ?? "data: null").slice(6)) as { type: string; employees: unknown[] } | null;
    });
    expect(first?.type).toBe("snapshot");
    expect(first?.employees.length).toBeGreaterThan(0);
  });

  test("clicking an employee opens the notebook, inbox and direct chat", async ({ page }) => {
    const note = tag("E2E defter notu");
    const task = tag("E2E gelen kutusu işi");
    seedEmployeeWork(note, task, "academic");

    await page.goto("/#/office");
    const list = page.getByRole("list", { name: "Çalışan durumları" });
    await list.getByRole("button", { name: /^Scholar,/ }).click();

    const panel = page.getByRole("region", { name: "Scholar" });
    await expect(panel).toBeVisible();
    await expect(page).toHaveURL(/employee=academic/);
    await expect(panel.getByText("Defter", { exact: true })).toBeVisible();
    await expect(panel.getByText(note)).toBeVisible();
    await expect(panel.getByText(task)).toBeVisible();
    await expect(panel.getByPlaceholder("Scholar: soru yaz…")).toBeVisible();
    await expect(panel.getByRole("button", { name: "Sor" })).toBeDisabled();

    await panel.getByRole("button", { name: "Paneli kapat" }).click();
    await expect(panel).toBeHidden();
  });
});

test.describe("task board", () => {
  test("shows the four columns and a finished task under Bitti", async ({ page }) => {
    const task = tag("E2E pano işi");
    seedEmployeeWork(tag("E2E pano notu"), task, "agenda");

    await page.goto("/#/board");
    await expect(page.getByRole("heading", { name: "Görev panosu", level: 1 })).toBeVisible();
    for (const column of ["Bekliyor", "Çalışıyor", "Onay bekliyor", "Bitti"]) {
      await expect(page.getByRole("region", { name: column, exact: true })).toBeVisible();
    }
    await expect(page.getByRole("region", { name: "Bitti", exact: true }).getByText(task)).toBeVisible();
  });
});
