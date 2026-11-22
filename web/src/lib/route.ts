import { useCallback, useEffect, useState } from "react";

// Not in the navigation, opened by link: "sheet" (#/sheet?id=3), "design-preview".
export const ROUTES = ["office", "chat", "today", "tomorrow", "week", "board", "reports", "status", "sheet", "design-preview"] as const;
export type Route = (typeof ROUTES)[number];

/** `#/week?week=2026-11-16` -> ["week", "week=2026-11-16"] */
function hashParts(): [string, string] {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const at = hash.indexOf("?");
  return at === -1 ? [hash, ""] : [hash.slice(0, at), hash.slice(at + 1)];
}

function current(): Route {
  if (window.location.pathname === "/design-preview") return "design-preview";
  const [path] = hashParts();
  return (ROUTES as readonly string[]).includes(path) ? (path as Route) : "office"; // the office is home
}

function useHashChange<T>(read: () => T): T {
  const [value, setValue] = useState<T>(read);
  useEffect(() => {
    const update = (): void => {
      setValue(read());
    };
    window.addEventListener("hashchange", update);
    return () => {
      window.removeEventListener("hashchange", update);
    };
  }, [read]);
  return value;
}

/** Tiny hash router (#/today): deep links work and the back button behaves on a phone. */
export function useRoute(): Route {
  return useHashChange(current);
}

const readParams = (): string => hashParts()[1];

/**
 * One query parameter of the current route (`#/week?week=2026-11-16`): survives a reload.
 * Setting it replaces the history entry (paging through weeks doesn't fill the back stack).
 */
export function useHashParam(name: string): [string | null, (value: string | null) => void] {
  const query = useHashChange(readParams);
  const value = new URLSearchParams(query).get(name);
  const set = useCallback(
    (next: string | null) => {
      const [path, rest] = hashParts();
      const params = new URLSearchParams(rest);
      if (next === null) params.delete(name);
      else params.set(name, next);
      const search = params.toString();
      window.history.replaceState(null, "", `#/${path}${search ? `?${search}` : ""}`);
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    },
    [name],
  );
  return [value, set];
}

export const href = (route: Route, params?: Record<string, string>): string => {
  const search = params ? new URLSearchParams(params).toString() : "";
  return `#/${route}${search ? `?${search}` : ""}`;
};
