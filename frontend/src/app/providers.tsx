import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { SessionProvider } from "@/features/session/context";
import { ExchangeSessionProvider } from "@/lib/exchange/session";
import { router } from "./router";
import { routerFuture } from "./routerFuture";
import type { ReactNode } from "react";

/**
 * Never retry 4xx client/semantic errors (notably 409 context_contradicted).
 * Network failures and 5xx errors retry up to 2 times.
 */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  const status =
    error != null && typeof error === "object" && "status" in error
      ? (error as { status?: unknown }).status
      : undefined;
  if (typeof status === "number" && status >= 400 && status < 500) {
    return false;
  }
  return failureCount < 2;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2000,
      retry: shouldRetryQuery,
      retryDelay: (attempt) => Math.min(500 * 2 ** attempt, 2000),
      refetchOnWindowFocus: false,
      refetchIntervalInBackground: false,
    },
    mutations: { retry: 0 },
  },
});

export function Providers({ children }: { children?: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <ExchangeSessionProvider>
          {children ?? <RouterProvider router={router} future={routerFuture} />}
        </ExchangeSessionProvider>
      </SessionProvider>
    </QueryClientProvider>
  );
}
