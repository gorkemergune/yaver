import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";

export interface Readiness {
  status: "ok" | "unavailable";
  database: "ok" | "unreachable";
}

export function useReadiness() {
  return useQuery({
    queryKey: ["health", "ready"],
    queryFn: ({ signal }) => apiGet<Readiness>("/health/ready", { signal }),
    refetchInterval: 30_000,
    retry: false,
  });
}
