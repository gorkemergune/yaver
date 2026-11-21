import { execFileSync } from "node:child_process";

import { expect, test } from "@playwright/test";

/**
 * Y2: a made-up X-Forwarded-For must not get past the wrong-password limit (5 / 10 min).
 * The attempts are sent from inside the web container (nginx sees 127.0.0.1): the lockout
 * then hits only that address, not the browser's, so the other tests can still log in.
 */
const WEB_CONTAINER = process.env.E2E_WEB_CONTAINER ?? "yaver-e2e-web-1";
if (!WEB_CONTAINER.startsWith("yaver-e2e-")) throw new Error(`refusing to touch ${WEB_CONTAINER}`);

function wrongLogin(forwardedFor: string): number {
  // busybox wget: -S prints the status line; an HTTP error exits non-zero
  const script =
    `wget -S -q -O /dev/null --header 'Content-Type: application/json' ` +
    `--header 'X-Forwarded-For: ${forwardedFor}' --post-data '{"password":"wrong"}' ` +
    `http://127.0.0.1/api/auth/login 2>&1 || true`;
  const out = execFileSync("docker", ["exec", WEB_CONTAINER, "sh", "-c", script], { encoding: "utf8" });
  const status = /HTTP\/1\.\d (\d{3})/.exec(out);
  if (!status) throw new Error(`no status line: ${out}`);
  return Number(status[1]);
}

test("changing X-Forwarded-For on every try still hits the login limit (through nginx)", () => {
  const codes = Array.from({ length: 7 }, (_, n) => wrongLogin(`10.9.8.${String(n)}`));
  // 401 until the limit, then 429 (earlier runs within 10 min may already be at 429)
  expect(codes.at(-1)).toBe(429);
  expect(codes.filter((code) => code === 401).length).toBeLessThanOrEqual(5);
  expect(codes.every((code) => code === 401 || code === 429)).toBe(true);
});
