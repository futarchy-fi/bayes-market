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
      retry: 1,
    },
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
