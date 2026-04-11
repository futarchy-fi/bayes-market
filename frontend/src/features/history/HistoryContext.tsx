import { createContext, useContext, useReducer, useCallback, type ReactNode } from "react";
import type { Command } from "./commands";

export const HISTORY_CAP = 50;

interface HistoryState {
  undoStack: Command[];
  redoStack: Command[];
}

type HistoryAction =
  | { type: "PUSH"; command: Command }
  | { type: "UNDO" }
  | { type: "REDO" }
  | { type: "CLEAR" };

function historyReducer(state: HistoryState, action: HistoryAction): HistoryState {
  switch (action.type) {
    case "PUSH": {
      const undoStack = [...state.undoStack, action.command].slice(-HISTORY_CAP);
      return { undoStack, redoStack: [] };
    }
    case "UNDO": {
      if (state.undoStack.length === 0) return state;
      const undoStack = state.undoStack.slice(0, -1);
      const command = state.undoStack[state.undoStack.length - 1]!;
      return { undoStack, redoStack: [...state.redoStack, command] };
    }
    case "REDO": {
      if (state.redoStack.length === 0) return state;
      const redoStack = state.redoStack.slice(0, -1);
      const command = state.redoStack[state.redoStack.length - 1]!;
      return { undoStack: [...state.undoStack, command], redoStack };
    }
    case "CLEAR":
      return { undoStack: [], redoStack: [] };
    default:
      return state;
  }
}

interface HistoryContextValue {
  /** Push a new command (already executed) onto the undo stack */
  push: (command: Command) => void;
  /** Undo the last command */
  undo: () => void;
  /** Redo the last undone command */
  redo: () => void;
  /** Clear all history */
  clear: () => void;
  canUndo: boolean;
  canRedo: boolean;
  /** Current undo stack (most recent last) */
  undoStack: readonly Command[];
  /** Current redo stack (most recent last) */
  redoStack: readonly Command[];
}

const HistoryCtx = createContext<HistoryContextValue | null>(null);

export function HistoryProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(historyReducer, { undoStack: [], redoStack: [] });

  const push = useCallback((command: Command) => {
    dispatch({ type: "PUSH", command });
  }, []);

  const undo = useCallback(() => {
    const command = state.undoStack[state.undoStack.length - 1];
    if (command) {
      command.undo();
      dispatch({ type: "UNDO" });
    }
  }, [state.undoStack]);

  const redo = useCallback(() => {
    const command = state.redoStack[state.redoStack.length - 1];
    if (command) {
      command.execute();
      dispatch({ type: "REDO" });
    }
  }, [state.redoStack]);

  const clear = useCallback(() => {
    dispatch({ type: "CLEAR" });
  }, []);

  return (
    <HistoryCtx.Provider
      value={{
        push,
        undo,
        redo,
        clear,
        canUndo: state.undoStack.length > 0,
        canRedo: state.redoStack.length > 0,
        undoStack: state.undoStack,
        redoStack: state.redoStack,
      }}
    >
      {children}
    </HistoryCtx.Provider>
  );
}

export function useHistory() {
  const ctx = useContext(HistoryCtx);
  if (!ctx) throw new Error("useHistory must be used within HistoryProvider");
  return ctx;
}

/** Returns the history context or null if not inside a HistoryProvider */
export function useOptionalHistory() {
  return useContext(HistoryCtx);
}
