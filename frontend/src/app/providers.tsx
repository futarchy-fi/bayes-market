import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router-dom";
import { SessionProvider } from "@/features/session/context";
import { router } from "./router";
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
        {children ?? <RouterProvider router={router} />}
      </SessionProvider>
    </QueryClientProvider>
  );
}
