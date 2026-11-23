import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
} from "react";
import { QueryClientContext, type QueryClient } from "@tanstack/react-query";
import { useInRouterContext, useLocation } from "react-router-dom";
import { logoutExchange, type ExchangeUnauthorizedDetail } from "./client";

const EXCHANGE_API = import.meta.env.VITE_EXCHANGE_API ?? "https://api.futarchy.ai";
const EXCHANGE_UNAUTHORIZED_EVENT = "exchange:unauthorized";

export const EXCHANGE_SESSION_STORAGE_KEY = "exchange-session";
export const EXCHANGE_RETURN_TO_STORAGE_KEY = "exchange-return-to";
export const EXCHANGE_SELECT_ACCOUNT_STORAGE_KEY = "exchange-select-account";
export const SESSION_EXPIRED_NOTICE =
  "Your session expired or was signed in elsewhere — sign in with GitHub again.";

const USER_EXCHANGE_QUERY_KEYS: ReadonlyArray<readonly string[]> = [
  ["exchange", "me"],
  ["exchange", "orders"],
  ["exchange", "portfolio"],
  ["exchange", "me-net"],
  ["exchange", "book", "orders"],
  ["exchange", "book", "positions"],
  ["exchange", "book-orders-mine"],
  ["exchange", "book-positions-mine"],
];

export interface ExchangeSession {
  apiKey: string;
  githubLogin: string;
}

export function parseExchangeFragment(hash: string): ExchangeSession | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const apiKey = params.get("auth") ?? "";
  if (!apiKey) return null;
  return { apiKey, githubLogin: params.get("login") ?? "" };
}

export function parseExchangeCallbackError(hash: string, search = ""): string | null {
  const hashParams = new URLSearchParams(hash.replace(/^#/, ""));
  const hashError = hashParams.get("error")?.trim();
  if (hashError) return hashError;
  const searchParams = new URLSearchParams(search.replace(/^\?/, ""));
  const searchError = searchParams.get("error")?.trim();
  if (searchError) return searchError;
  return null;
}

/**
 * Validates that a post-login return path is a safe same-origin relative path
 * (starts with `/`, never `//`, no backslashes/control chars, and not `/exchange/callback`).
 */
export function isSafeReturnTo(path: string | null | undefined): path is string {
  if (!path || typeof path !== "string") return false;
  if (!path.startsWith("/") || path.startsWith("//")) return false;
  if (path.includes("\\") || /[\u0000-\u001f]/.test(path)) return false;
  if (
    path === "/exchange/callback" ||
    path.startsWith("/exchange/callback/") ||
    path.startsWith("/exchange/callback?") ||
    path.startsWith("/exchange/callback#")
  ) {
    return false;
  }
  return true;
}

export function saveReturnTo(returnTo?: string): void {
  try {
    const candidate =
      returnTo !== undefined
        ? returnTo
        : typeof window !== "undefined"
          ? `${window.location.pathname}${window.location.search}${window.location.hash}`
          : undefined;
    if (isSafeReturnTo(candidate)) {
      sessionStorage.setItem(EXCHANGE_RETURN_TO_STORAGE_KEY, candidate);
    } else if (returnTo !== undefined) {
      sessionStorage.removeItem(EXCHANGE_RETURN_TO_STORAGE_KEY);
    }
  } catch {
    // Ignore storage access errors (e.g. strict browser privacy settings).
  }
}

export function consumeReturnTo(): string | null {
  try {
    const stored = sessionStorage.getItem(EXCHANGE_RETURN_TO_STORAGE_KEY);
    sessionStorage.removeItem(EXCHANGE_RETURN_TO_STORAGE_KEY);
    return isSafeReturnTo(stored) ? stored : null;
  } catch {
    return null;
  }
}

export function clearSelectAccountFlag(): void {
  try {
    sessionStorage.removeItem(EXCHANGE_SELECT_ACCOUNT_STORAGE_KEY);
  } catch {
    // Ignore storage access errors.
  }
}

function shouldSelectAccount(): boolean {
  try {
    return sessionStorage.getItem(EXCHANGE_SELECT_ACCOUNT_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Builds the GitHub OAuth login URL, appending `?prompt=select_account` after
 * an explicit sign-out so the user can pick a different GitHub account. When
 * `returnTo` is provided, stores it safely in `sessionStorage["exchange-return-to"]`.
 */
export function getGithubLoginUrl(returnTo?: string): string {
  if (returnTo !== undefined) {
    saveReturnTo(returnTo);
  }
  const base = `${EXCHANGE_API}/v1/auth/github/login`;
  return shouldSelectAccount() ? `${base}?prompt=select_account` : base;
}

/**
 * Saves a safe `returnTo` destination (defaulting to the current relative URL)
 * and navigates to the GitHub OAuth login endpoint.
 */
export function startGithubLogin(returnTo?: string): void {
  saveReturnTo(returnTo);
  const url = getGithubLoginUrl();
  if (typeof window !== "undefined") {
    window.location.assign(url);
  }
}

function loadSession(): ExchangeSession {
  try {
    const parsed = JSON.parse(
      localStorage.getItem(EXCHANGE_SESSION_STORAGE_KEY) ?? "null",
    ) as Partial<ExchangeSession> | null;
    if (parsed?.apiKey) return { apiKey: parsed.apiKey, githubLogin: parsed.githubLogin ?? "" };
  } catch {
    // Ignore corrupt local state.
  }
  return { apiKey: "", githubLogin: "" };
}

function clearUserExchangeQueries(queryClient: QueryClient | undefined): void {
  if (!queryClient) return;
  for (const queryKey of USER_EXCHANGE_QUERY_KEYS) {
    queryClient.removeQueries({ queryKey });
  }
}

export interface ExchangeSessionValue {
  session: ExchangeSession;
  isSignedIn: boolean;
  sessionNotice: string | null;
  clearSessionNotice: () => void;
  setSession: (session: ExchangeSession) => void;
  signOut: () => void;
}

const ExchangeSessionContext = createContext<ExchangeSessionValue | null>(null);

export function ExchangeSessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useContext(QueryClientContext);
  const [session, setSessionState] = useState<ExchangeSession>(loadSession);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);
  const sessionRef = useRef<ExchangeSession>(session);
  sessionRef.current = session;

  const setSession = useCallback((next: ExchangeSession) => {
    try {
      localStorage.setItem(EXCHANGE_SESSION_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Ignore storage write errors.
    }
    clearSelectAccountFlag();
    sessionRef.current = next;
    setSessionState(next);
    setSessionNotice(null);
  }, []);

  const signOut = useCallback(() => {
    const currentKey = sessionRef.current.apiKey;
    if (currentKey) {
      void logoutExchange(currentKey);
    }
    try {
      localStorage.removeItem(EXCHANGE_SESSION_STORAGE_KEY);
    } catch {
      // Ignore storage errors.
    }
    try {
      sessionStorage.setItem(EXCHANGE_SELECT_ACCOUNT_STORAGE_KEY, "1");
    } catch {
      // Ignore storage errors.
    }
    const empty = { apiKey: "", githubLogin: "" };
    sessionRef.current = empty;
    setSessionState(empty);
    setSessionNotice(null);
    clearUserExchangeQueries(queryClient);
  }, [queryClient]);

  const clearSessionNotice = useCallback(() => {
    setSessionNotice(null);
  }, []);

  // Auto-recover when any authenticated request returns HTTP 401.
  useEffect(() => {
    const handleUnauthorized = (event: Event) => {
      const detail = (event as CustomEvent<ExchangeUnauthorizedDetail>).detail;
      const failedApiKey = detail?.apiKey;
      if (!failedApiKey || !sessionRef.current.apiKey || sessionRef.current.apiKey !== failedApiKey) {
        return;
      }
      try {
        localStorage.removeItem(EXCHANGE_SESSION_STORAGE_KEY);
      } catch {
        // Ignore storage errors.
      }
      const empty = { apiKey: "", githubLogin: "" };
      sessionRef.current = empty;
      setSessionState(empty);
      clearUserExchangeQueries(queryClient);
      setSessionNotice(SESSION_EXPIRED_NOTICE);
    };
    window.addEventListener(EXCHANGE_UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => window.removeEventListener(EXCHANGE_UNAUTHORIZED_EVENT, handleUnauthorized);
  }, [queryClient]);

  // Cross-tab sync: reflect sign-in, sign-out, or account switches from other tabs.
  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.storageArea && event.storageArea !== localStorage) return;
      if (event.key !== null && event.key !== EXCHANGE_SESSION_STORAGE_KEY) return;
      const prevKey = sessionRef.current.apiKey;
      const next = loadSession();
      sessionRef.current = next;
      setSessionState(next);
      if (next.apiKey) {
        clearSelectAccountFlag();
        setSessionNotice(null);
        if (prevKey !== next.apiKey) {
          clearUserExchangeQueries(queryClient);
        }
      } else if (prevKey) {
        clearUserExchangeQueries(queryClient);
      }
    };
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [queryClient]);

  return (
    <ExchangeSessionContext.Provider
      value={{
        session,
        isSignedIn: Boolean(session.apiKey),
        sessionNotice,
        clearSessionNotice,
        setSession,
        signOut,
      }}
    >
      {children}
    </ExchangeSessionContext.Provider>
  );
}

export function useExchangeSession() {
  const value = useContext(ExchangeSessionContext);
  if (!value) throw new Error("useExchangeSession must be used within ExchangeSessionProvider");
  return value;
}

function RouterGithubSignInLink({
  returnTo,
  style,
  className,
  children,
}: {
  returnTo?: string;
  style?: CSSProperties;
  className?: string;
  children: ReactNode;
}) {
  const location = useLocation();
  const target = returnTo ?? `${location.pathname}${location.search}${location.hash}`;
  const href = getGithubLoginUrl();
  const handleClick = (_event: MouseEvent<HTMLAnchorElement>) => {
    saveReturnTo(target);
  };
  return (
    <a href={href} onClick={handleClick} style={style} className={className}>
      {children}
    </a>
  );
}

/**
 * Shared GitHub sign-in link that appends `?prompt=select_account` after sign-out
 * and persists a safe relative `returnTo` path in `sessionStorage["exchange-return-to"]`.
 */
export function GithubSignInLink({
  returnTo,
  style,
  className,
  children,
}: {
  returnTo?: string;
  style?: CSSProperties;
  className?: string;
  children: ReactNode;
}) {
  const inRouter = useInRouterContext();
  if (inRouter) {
    return (
      <RouterGithubSignInLink returnTo={returnTo} style={style} className={className}>
        {children}
      </RouterGithubSignInLink>
    );
  }
  const href = getGithubLoginUrl();
  return (
    <a href={href} onClick={() => saveReturnTo(returnTo)} style={style} className={className}>
      {children}
    </a>
  );
}
