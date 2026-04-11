import { useCallback } from "react";
import { useAssumptions, type Assumption } from "@/features/assumptions/AssumptionContext";
import { useHistory } from "./HistoryContext";
import { AssumptionAddCommand, AssumptionRemoveCommand, AssumptionClearAllCommand } from "./commands";

/**
 * Wraps useAssumptions() with history tracking.
 * Returns the same API surface but each mutation pushes a command onto the undo stack.
 */
export function useHistoryAssumptions() {
  const assumptions = useAssumptions();
  const history = useHistory();

  const addAssumption = useCallback(
    (a: Assumption) => {
      const previous = assumptions.getAssumption(a.variableId);
      const cmd = new AssumptionAddCommand({
        assumption: a,
        previousAssumption: previous,
        addAssumption: assumptions.addAssumption,
        removeAssumption: assumptions.removeAssumption,
      });
      cmd.execute();
      history.push(cmd);
    },
    [assumptions, history],
  );

  const removeAssumption = useCallback(
    (variableId: string) => {
      const existing = assumptions.getAssumption(variableId);
      if (!existing) return;
      const cmd = new AssumptionRemoveCommand({
        removedAssumption: existing,
        addAssumption: assumptions.addAssumption,
        removeAssumption: assumptions.removeAssumption,
      });
      cmd.execute();
      history.push(cmd);
    },
    [assumptions, history],
  );

  const clearAll = useCallback(() => {
    if (assumptions.assumptions.length === 0) return;
    const cmd = new AssumptionClearAllCommand({
      previousAssumptions: assumptions.assumptions,
      setAllAssumptions: assumptions.setAllAssumptions,
      clearAll: assumptions.clearAll,
    });
    cmd.execute();
    history.push(cmd);
  }, [assumptions, history]);

  return {
    ...assumptions,
    addAssumption,
    removeAssumption,
    clearAll,
  };
}
