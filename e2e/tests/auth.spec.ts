import { expect, test } from "@playwright/test";

import { API_URL, PASSWORD } from "../helpers/env";

test.describe("API and login", () => {
  test("API is really up: /api/health/ready 200 (direct and through nginx)", async ({ request }) => {
    const direct = await request.get(`${API_URL}/api/health/ready`);
    expect(direct.status()).toBe(200);
    expect(await direct.json()).toEqual({ status: "ok", database: "ok" });

    const proxied = await request.get("/api/health/ready");
    expect(proxied.status()).toBe(200);

    const live = await request.get("/health");
    expect(live.status()).toBe(200);
  });

  test("guarded endpoints answer 401 without a session", async ({ playwright }) => {
    const anon = await playwright.request.newContext({ baseURL: API_URL, storageState: { cookies: [], origins: [] } });
    for (const path of [
      "/api/office/snapshot",
      "/api/team",
      "/api/conversations/latest",
      "/api/usage/month",
      "/api/office/board",
      "/api/office/stream",
      "/api/employees/academic/notes",
      "/api/devices",
    ]) {
      const res = await anon.get(path);
      expect(res.status(), path).toBe(401);
    }
    const chat = await anon.post("/api/chat/stream", { data: { message: "selam" } });
    expect(chat.status()).toBe(401);
    const undo = await anon.post("/api/changes/00000000-0000-0000-0000-000000000000/undo");
    expect(undo.status()).toBe(401);
    const status = await anon.get("/api/auth/status");
    expect(await status.json()).toEqual({ enabled: true, authenticated: false });
    await anon.dispose();
  });

  test.describe("login screen", () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test("shows the login screen, rejects a wrong password, accepts the right one", async ({ page }) => {
      await page.goto("/");
      const password = page.locator("#password");
      await expect(password).toBeVisible();
      await expect(page.getByRole("heading", { name: "Yaver" })).toBeVisible();

      await password.fill("definitely-wrong");
      await page.locator("form button[type=submit]").click();
      await expect(page.getByRole("alert")).not.toBeEmpty();
      await expect(password).toBeVisible();

      await password.fill(PASSWORD);
      await page.locator("form button[type=submit]").click();
      await expect(password).toBeHidden();
      await expect(page.getByRole("heading", { name: "Ofis", level: 1 })).toBeVisible();

      // the session survives a reload (httpOnly cookie)
      await page.reload();
      await expect(page.getByRole("heading", { name: "Ofis", level: 1 })).toBeVisible();
      await expect(page.locator("#password")).toHaveCount(0);
    });
  });
});

test("O1: a configuration mistake the API survived shows a warning banner", async ({ page }) => {
  await page.route("**/api/team", async (route) => {
    const response = await route.fetch();
    const team = (await response.json()) as Record<string, unknown>;
    team.config_problems = [
      { source: ".env", field: "BRIEFING_TIME", message: "expected HH:MM, got '9h'", fallback: "09:00" },
      { source: "agents.yaml", field: null, message: "agents.0.tools: unknown tool", fallback: "agents.example.yaml" },
    ];
    await route.fulfill({ response, json: team });
  });
  await page.goto("/#/plan");
  const banner = page.getByRole("alert").filter({ hasText: "Ayar dosyasında hata var" });
  await expect(banner).toBeVisible();
  await expect(banner.getByText('.env: BRIEFING_TIME geçersiz, "09:00" kullanılıyor.')).toBeVisible();
  await expect(banner.getByText("agents.yaml okunamadı, agents.example.yaml kullanılıyor.")).toBeVisible();
});
