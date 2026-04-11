import { QueryClient, QueryClientProvider, type UseQueryResult, type UseMutationResult } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SessionProvider } from "@/features/session/context";
import { routerFuture } from "@/app/routerFuture";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { vi } from "vitest";

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

function TestProviders({
  children,
  initialEntries,
}: {
  children: ReactNode;
  initialEntries?: string[];
}) {
  const qc = createTestQueryClient();
  return (
    <QueryClientProvider client={qc}>
      <SessionProvider>
        <MemoryRouter future={routerFuture} initialEntries={initialEntries}>
          {children}
        </MemoryRouter>
      </SessionProvider>
    </QueryClientProvider>
  );
}

export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper"> & { route?: string; initialEntries?: string[] },
) {
  const { route, initialEntries, ...renderOptions } = options ?? {};

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <TestProviders initialEntries={initialEntries ?? (route ? [route] : undefined)}>
        {children}
      </TestProviders>
    );
  }

  return render(ui, { wrapper: Wrapper, ...renderOptions });
}

export function createMockQueryResult<T>(
  overrides?: Partial<UseQueryResult<T, Error>>,
): UseQueryResult<T, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isSuccess: false,
    isError: false,
    isPending: false,
    isLoadingError: false,
    isRefetchError: false,
    status: "pending",
    fetchStatus: "idle",
    isFetching: false,
    isPlaceholderData: false,
    isRefetching: false,
    isStale: false,
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    errorUpdateCount: 0,
    isFetched: false,
    isFetchedAfterMount: false,
    isInitialLoading: false,
    isPaused: false,
    isEnabled: true,
    refetch: vi.fn(),
    promise: Promise.resolve(undefined as never),
    ...overrides,
  } as UseQueryResult<T, Error>;
}

export function createMockMutationResult<TData = unknown, TError = Error, TVariables = unknown, TContext = unknown>(
  overrides?: Partial<UseMutationResult<TData, TError, TVariables, TContext>>,
): UseMutationResult<TData, TError, TVariables, TContext> {
  return {
    data: undefined,
    error: null,
    isError: false,
    isIdle: true,
    isPending: false,
    isSuccess: false,
    status: "idle",
    variables: undefined,
    context: undefined,
    failureCount: 0,
    failureReason: null,
    submittedAt: 0,
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    reset: vi.fn(),
    isPaused: false,
    ...overrides,
  } as UseMutationResult<TData, TError, TVariables, TContext>;
}
