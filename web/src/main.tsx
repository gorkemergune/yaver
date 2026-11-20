import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { AUTH_KEY } from "./api/auth";
import { ApiError } from "./api/client";
import { registerServiceWorker } from "./lib/push";
import "@fontsource-variable/inter";
import "@fontsource-variable/space-grotesk";
import "./design/design.css";
import "./index.css";

const queryClient: QueryClient = new QueryClient({
  // A 401 anywhere (session expired, logged out elsewhere): ask the server again,
  // the app then shows the login screen.
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (error instanceof ApiError && error.status === 401 && query.queryKey[0] !== AUTH_KEY[0]) {
        void queryClient.invalidateQueries({ queryKey: AUTH_KEY });
      }
    },
  }),
  defaultOptions: {
    queries: { staleTime: 30_000, refetchOnWindowFocus: true },
  },
});

registerServiceWorker();
// A push arrived while the app is open: the new chat message shows up right away.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("message", (event: MessageEvent<{ type?: string }>) => {
    if (event.data.type === "push") void queryClient.invalidateQueries();
  });
}

const root = document.getElementById("root");
if (!root) throw new Error("#root element not found");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
