import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { SessionProvider } from "@/features/session/context";
import { ExchangeSessionProvider } from "@/lib/exchange/session";
import { router } from "./router";
import { routerFuture } from "./routerFuture";
import type { ReactNode } from "react";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2000,
      retry: 2,
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
