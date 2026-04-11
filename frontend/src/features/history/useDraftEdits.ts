import { useState, useCallback } from "react";
import { useOptionalHistory } from "./HistoryContext";
import { ProbabilityEditCommand, type DraftEdit } from "./commands";

/**
 * Local draft buffer for probability edits with undo/redo support.
 *
 * Staged edits are stored locally. On undo/redo the draft map is updated.
 * The consumer calls `commit()` to submit all staged drafts to the server.
 */
export function useDraftEdits() {
  const history = useOptionalHistory();

  // Map from "entryIndex::outcomeId" to drafted probability
  const [drafts, setDrafts] = useState<Map<string, DraftEdit>>(new Map());

  const draftKey = (entryIndex: number, outcomeId: string) => `${entryIndex}::${outcomeId}`;

  const applyDrafts = useCallback((edits: DraftEdit[]) => {
    setDrafts((prev) => {
      const next = new Map(prev);
      for (const edit of edits) {
        next.set(draftKey(edit.entryIndex, edit.outcomeId), edit);
      }
      return next;
    });
  }, []);

  const revertDrafts = useCallback((edits: DraftEdit[]) => {
    setDrafts((prev) => {
      const next = new Map(prev);
      for (const edit of edits) {
        const key = draftKey(edit.entryIndex, edit.outcomeId);
        if (!edit.hadPriorDraft) {
          // No draft existed before this edit — remove it entirely
          next.delete(key);
        } else {
          // Restore to previous draft value
          next.set(key, { ...edit, probability: edit.previousProbability });
        }
      }
      return next;
    });
  }, []);

  const stageDraft = useCallback(
    (edit: DraftEdit) => {
      // Look up existing draft to track previous value
      const key = draftKey(edit.entryIndex, edit.outcomeId);
      const existing = drafts.get(key);
      const hadPriorDraft = existing !== undefined;
      const previousProbability = existing?.probability ?? edit.previousProbability;

      const draftWithPrev: DraftEdit = { ...edit, previousProbability, hadPriorDraft };
      const cmd = new ProbabilityEditCommand({
        drafts: [draftWithPrev],
        applyDrafts,
        revertDrafts,
      });
      cmd.execute();
      history?.push(cmd);
    },
    [drafts, history, applyDrafts, revertDrafts],
  );

  const getDraft = useCallback(
    (entryIndex: number, outcomeId: string): number | undefined => {
      return drafts.get(draftKey(entryIndex, outcomeId))?.probability;
    },
    [drafts],
  );

  const clearDrafts = useCallback(() => {
    setDrafts(new Map());
  }, []);

  const hasDrafts = drafts.size > 0;

  const allDrafts = useCallback(() => Array.from(drafts.values()), [drafts]);

  return {
    stageDraft,
    getDraft,
    clearDrafts,
    hasDrafts,
    allDrafts,
    drafts,
  };
}
