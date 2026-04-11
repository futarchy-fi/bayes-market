import { useHistory } from "./HistoryContext";
import { useUndoRedoKeyboard } from "./useUndoRedoKeyboard";

export function UndoRedoToolbar() {
  const { undo, redo, canUndo, canRedo, undoStack, redoStack } = useHistory();
  useUndoRedoKeyboard();

  return (
    <div style={toolbarStyle}>
      <button
        onClick={undo}
        disabled={!canUndo}
        style={canUndo ? btnStyle : disabledBtnStyle}
        title={canUndo ? `Undo: ${undoStack[undoStack.length - 1]?.description}` : "Nothing to undo"}
        aria-label="Undo"
      >
        Undo
      </button>
      <button
        onClick={redo}
        disabled={!canRedo}
        style={canRedo ? btnStyle : disabledBtnStyle}
        title={canRedo ? `Redo: ${redoStack[redoStack.length - 1]?.description}` : "Nothing to redo"}
        aria-label="Redo"
      >
        Redo
      </button>
      {(canUndo || canRedo) && (
        <span style={statusStyle}>
          {undoStack.length} undo{undoStack.length !== 1 ? "s" : ""}
          {canRedo && ` / ${redoStack.length} redo${redoStack.length !== 1 ? "s" : ""}`}
        </span>
      )}
    </div>
  );
}

const toolbarStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "var(--space-sm)",
  padding: "var(--space-xs) 0",
};

const btnStyle: React.CSSProperties = {
  padding: "4px 12px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg-surface)",
  color: "var(--color-text)",
  fontSize: "0.8rem",
  fontWeight: 500,
  cursor: "pointer",
};

const disabledBtnStyle: React.CSSProperties = {
  ...btnStyle,
  opacity: 0.4,
  cursor: "default",
};

const statusStyle: React.CSSProperties = {
  fontSize: "0.75rem",
  color: "var(--color-text-muted)",
};
