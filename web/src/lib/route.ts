import { useEffect, useState } from "react";

// "design-preview" is not in the navigation: opened by link (#/design-preview or /design-preview).
export const ROUTES = ["chat", "today", "tomorrow", "week", "status", "design-preview"] as const;
export type Route = (typeof ROUTES)[number];

function current(): Route {
  if (window.location.pathname === "/design-preview") return "design-preview";
  const hash = window.location.hash.replace(/^#\/?/, "");
  return (ROUTES as readonly string[]).includes(hash) ? (hash as Route) : "chat";
}

/** Tiny hash router (#/today): deep links work and the back button behaves on a phone. */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(current);
  useEffect(() => {
    const update = (): void => {
      setRoute(current());
    };
    window.addEventListener("hashchange", update);
    return () => {
      window.removeEventListener("hashchange", update);
    };
  }, []);
  return route;
}

export const href = (route: Route): string => `#/${route}`;
