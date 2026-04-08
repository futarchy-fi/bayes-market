import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import type { Session } from "@/lib/api/types";

const STORAGE_KEY = "bayes-session";

function loadSession(): Session {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Session;
      return { accountId: parsed.accountId ?? "", agentId: parsed.agentId ?? "" };
    }
  } catch {
    // ignore corrupt storage
  }
  return { accountId: "", agentId: "" };
}

function saveSession(session: Session): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

interface SessionContextValue {
  session: Session;
  setAccountId: (id: string) => void;
  setAgentId: (id: string) => void;
  isConfigured: boolean;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>(loadSession);

  const setAccountId = useCallback((accountId: string) => {
    setSession((prev) => {
      const next = { ...prev, accountId };
      saveSession(next);
      return next;
    });
  }, []);

  const setAgentId = useCallback((agentId: string) => {
    setSession((prev) => {
      const next = { ...prev, agentId };
      saveSession(next);
      return next;
    });
  }, []);

  return (
    <SessionContext.Provider
      value={{ session, setAccountId, setAgentId, isConfigured: session.accountId.length > 0 }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
