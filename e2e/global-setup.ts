import { mkdirSync, writeFileSync } from "node:fs";

import { request, type FullConfig } from "@playwright/test";

import { API_URL, PASSWORD, WEB_URL } from "./helpers/env";

/** Waits for the isolated stack, logs in once and stores the session cookie for all tests. */
export default async function globalSetup(_config: FullConfig): Promise<void> {
  const api = await request.newContext();
  const deadline = Date.now() + 60_000;
  for (;;) {
    try {
      const res = await api.get(`${API_URL}/api/health/ready`, { timeout: 5_000 });
      if (res.ok()) break;
    } catch {
      // not up yet
    }
    if (Date.now() > deadline) throw new Error(`e2e api not ready at ${API_URL} - run e2e/stack.sh up`);
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  await api.dispose();

  mkdirSync(".auth", { recursive: true });
  const web = await request.newContext({ baseURL: WEB_URL });
  const login = await web.post("/api/auth/login", { data: { password: PASSWORD } });
  if (!login.ok()) throw new Error(`login failed: ${String(login.status())} ${await login.text()}`);
  const state = await web.storageState();
  // Fresh database: skip the first-run setup card so the chat shows the composer.
  state.origins = [
    { origin: new URL(WEB_URL).origin, localStorage: [{ name: "yaver.onboarding.skipped", value: "1" }] },
  ];
  writeFileSync(".auth/state.json", JSON.stringify(state, null, 2));
  await web.dispose();
}
