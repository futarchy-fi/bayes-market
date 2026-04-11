import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

export interface Assumption {
  variableId: string;
  outcomeId: string;
  /** Display label for the assumption */
  label: string;
}

interface AssumptionState {
  assumptions: Assumption[];
  addAssumption: (a: Assumption) => void;
  removeAssumption: (variableId: string) => void;
  clearAll: () => void;
  hasAssumption: (variableId: string) => boolean;
  getAssumption: (variableId: string) => Assumption | undefined;
  /** Context array for API calls */
  contextPayload: Array<{ variableId: string; outcomeId: string }>;
}

const AssumptionCtx = createContext<AssumptionState | null>(null);

export function AssumptionProvider({ children }: { children: ReactNode }) {
  const [assumptions, setAssumptions] = useState<Assumption[]>([]);

  const addAssumption = useCallback((a: Assumption) => {
    setAssumptions((prev) => {
      const filtered = prev.filter((p) => p.variableId !== a.variableId);
      return [...filtered, a];
    });
  }, []);

  const removeAssumption = useCallback((variableId: string) => {
    setAssumptions((prev) => prev.filter((p) => p.variableId !== variableId));
  }, []);

  const clearAll = useCallback(() => setAssumptions([]), []);

  const hasAssumption = useCallback(
    (variableId: string) => assumptions.some((a) => a.variableId === variableId),
    [assumptions],
  );

  const getAssumption = useCallback(
    (variableId: string) => assumptions.find((a) => a.variableId === variableId),
    [assumptions],
  );

  const contextPayload = assumptions.map((a) => ({
    variableId: a.variableId,
    outcomeId: a.outcomeId,
  }));

  return (
    <AssumptionCtx.Provider
      value={{ assumptions, addAssumption, removeAssumption, clearAll, hasAssumption, getAssumption, contextPayload }}
    >
      {children}
    </AssumptionCtx.Provider>
  );
}

export function useAssumptions() {
  const ctx = useContext(AssumptionCtx);
  if (!ctx) throw new Error("useAssumptions must be used within AssumptionProvider");
  return ctx;
}
