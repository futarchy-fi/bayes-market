import { useEffect } from "react";
import { useHistory } from "./HistoryContext";

/**
 * Returns true if the active element is an input/textarea/select/contenteditable,
 * meaning native browser undo should be used instead.
 */
export function isEditableElement(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if ((el as HTMLElement).isContentEditable || (el as HTMLElement).contentEditable === "true") return true;
  return false;
}

/**
 * Listens for Ctrl+Z (undo) and Ctrl+Shift+Z / Ctrl+Y (redo) on the document.
 * Skips events when an editable element is focused.
 */
export function useUndoRedoKeyboard() {
  const { undo, redo, canUndo, canRedo } = useHistory();

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (isEditableElement(document.activeElement)) return;

      const isCtrl = e.ctrlKey || e.metaKey;
      if (!isCtrl) return;

      if (e.key === "z" && !e.shiftKey) {
        if (canUndo) {
          e.preventDefault();
          undo();
        }
      } else if ((e.key === "z" && e.shiftKey) || e.key === "y") {
        if (canRedo) {
          e.preventDefault();
          redo();
        }
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [undo, redo, canUndo, canRedo]);
}
