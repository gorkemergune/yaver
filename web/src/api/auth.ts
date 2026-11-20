import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";

export interface AuthStatus {
  enabled: boolean; // APP_PASSWORD set on the server
  authenticated: boolean;
}

export const AUTH_KEY = ["auth"] as const;

export function useAuthStatus() {
  return useQuery({
    queryKey: AUTH_KEY,
    queryFn: ({ signal }) => apiGet<AuthStatus>("/auth/status", { signal }),
    staleTime: 5 * 60_000,
    retry: 1,
  });
}

export type LoginResult = { ok: true } | { ok: false; error: "wrong_password" | "too_many_attempts" | "network"; retryAfter?: number };

/** POST /api/auth/login: the server sets an httpOnly cookie; nothing is kept in JS. */
export async function login(password: string): Promise<LoginResult> {
  let response: Response;
  try {
    response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ password, client: "web" }),
    });
  } catch {
    return { ok: false, error: "network" };
  }
  if (response.ok) return { ok: true };
  if (response.status === 429) {
    return { ok: false, error: "too_many_attempts", retryAfter: Number(response.headers.get("Retry-After")) || 60 };
  }
  if (response.status === 401) return { ok: false, error: "wrong_password" };
  return { ok: false, error: "network" };
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
}
