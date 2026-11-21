import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { WEB_URL } from "../helpers/env";

/**
 * Y1: an open stream must not hold a database connection. The pool is 5 + 10; with the bug,
 * 15 open office tabs (SSE) kept one connection each "idle in transaction" and every other
 * request waited 30 s for the pool, then failed (/api/health/ready included).
 * The streams are opened from Node: a browser allows only 6 connections per host.
 */
const STREAMS = 18;

function cookieHeader(): string {
  const state = JSON.parse(readFileSync(".auth/state.json", "utf8")) as {
    cookies: { name: string; value: string }[];
  };
  return state.cookies.map((c) => `${c.name}=${c.value}`).join("; ");
}

async function timed(path: string, cookie: string): Promise<{ status: number; ms: number }> {
  const started = performance.now();
  const res = await fetch(`${WEB_URL}${path}`, {
    headers: { cookie },
    signal: AbortSignal.timeout(10_000),
  });
  await res.arrayBuffer();
  return { status: res.status, ms: performance.now() - started };
}

test(`${String(STREAMS)} open office streams: the board and /health/ready still answer at once`, async () => {
  const cookie = cookieHeader();
  const controllers: AbortController[] = [];
  try {
    // open every stream and wait for its first event (the snapshot): each one passed require_auth
    await Promise.all(
      Array.from({ length: STREAMS }, async () => {
        const controller = new AbortController();
        controllers.push(controller);
        const res = await fetch(`${WEB_URL}/api/office/stream`, { headers: { cookie }, signal: controller.signal });
        expect(res.status).toBe(200);
        const reader = res.body!.getReader();
        const decoder = new TextDecoder();
        let text = "";
        while (!text.includes("data: ")) {
          const { value, done } = await reader.read();
          if (done) throw new Error("stream closed early");
          text += decoder.decode(value, { stream: true });
        }
      }),
    );

    const board = await timed("/api/office/board", cookie);
    const ready = await timed("/api/health/ready", cookie);
    expect(board.status).toBe(200);
    expect(ready.status).toBe(200);
    expect(board.ms).toBeLessThan(5_000);
    expect(ready.ms).toBeLessThan(5_000);
  } finally {
    for (const controller of controllers) controller.abort();
  }
});
