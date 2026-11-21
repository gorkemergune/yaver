export const WEB_URL = process.env.E2E_WEB_URL ?? "http://127.0.0.1:8090";
export const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:8001";
/** Fixed in e2e/docker-compose.e2e.yml (APP_PASSWORD). */
export const PASSWORD = process.env.E2E_PASSWORD ?? "e2e-test-password";
/** Hard cap for all @live tests together (USD, from llm_usage of the e2e database). */
export const LIVE_BUDGET_USD = 0.3;
/** The UI must show the answer, or an error, within this time. */
export const ANSWER_TIMEOUT_MS = 60_000;
