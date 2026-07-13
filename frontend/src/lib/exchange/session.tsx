import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

const STORAGE_KEY = "exchange-session";

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

function loadSession(): ExchangeSession {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as Partial<ExchangeSession> | null;
    if (parsed?.apiKey) return { apiKey: parsed.apiKey, githubLogin: parsed.githubLogin ?? "" };
  } catch {
    // Ignore corrupt local state.
  }
  return { apiKey: "", githubLogin: "" };
}

interface ExchangeSessionValue {
  session: ExchangeSession;
  isSignedIn: boolean;
  setSession: (session: ExchangeSession) => void;
  signOut: () => void;
}

const ExchangeSessionContext = createContext<ExchangeSessionValue | null>(null);

export function ExchangeSessionProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<ExchangeSession>(loadSession);
  const setSession = useCallback((next: ExchangeSession) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    setSessionState(next);
  }, []);
  const signOut = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setSessionState({ apiKey: "", githubLogin: "" });
  }, []);

  return (
    <ExchangeSessionContext.Provider value={{ session, isSignedIn: Boolean(session.apiKey), setSession, signOut }}>
      {children}
    </ExchangeSessionContext.Provider>
  );
}

export function useExchangeSession() {
  const value = useContext(ExchangeSessionContext);
  if (!value) throw new Error("useExchangeSession must be used within ExchangeSessionProvider");
  return value;
}
