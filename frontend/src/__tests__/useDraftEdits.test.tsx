import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { HistoryProvider, useHistory } from "@/features/history/HistoryContext";
import { useDraftEdits } from "@/features/history/useDraftEdits";
import type { ReactNode } from "react";

function wrapper({ children }: { children: ReactNode }) {
  return <HistoryProvider>{children}</HistoryProvider>;
}

function useTestHook() {
  const history = useHistory();
  const drafts = useDraftEdits();
  return { history, drafts };
}

describe("useDraftEdits", () => {
  it("starts with no drafts", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    expect(result.current.drafts.hasDrafts).toBe(false);
    expect(result.current.drafts.allDrafts()).toEqual([]);
  });

  it("staging a draft makes it retrievable", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    act(() => {
      result.current.drafts.stageDraft({
        entryIndex: 0,
        outcomeId: "o1",
        probability: 0.7,
        context: [],
        previousProbability: 0.5,
      });
    });
    expect(result.current.drafts.hasDrafts).toBe(true);
    expect(result.current.drafts.getDraft(0, "o1")).toBe(0.7);
  });

  it("staging a draft pushes to history", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    act(() => {
      result.current.drafts.stageDraft({
        entryIndex: 0,
        outcomeId: "o1",
        probability: 0.7,
        context: [],
        previousProbability: 0.5,
      });
    });
    expect(result.current.history.canUndo).toBe(true);
  });

  it("undo reverts a staged draft", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    act(() => {
      result.current.drafts.stageDraft({
        entryIndex: 0,
        outcomeId: "o1",
        probability: 0.7,
        context: [],
        previousProbability: 0.5,
      });
    });
    act(() => result.current.history.undo());
    // After undo, draft should be removed (reverted to server value)
    expect(result.current.drafts.getDraft(0, "o1")).toBeUndefined();
  });

  it("redo re-applies a reverted draft", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    act(() => {
      result.current.drafts.stageDraft({
        entryIndex: 0,
        outcomeId: "o1",
        probability: 0.7,
        context: [],
        previousProbability: 0.5,
      });
    });
    act(() => result.current.history.undo());
    act(() => result.current.history.redo());
    expect(result.current.drafts.getDraft(0, "o1")).toBe(0.7);
  });

  it("clearDrafts removes all drafts", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    act(() => {
      result.current.drafts.stageDraft({
        entryIndex: 0,
        outcomeId: "o1",
        probability: 0.7,
        context: [],
        previousProbability: 0.5,
      });
    });
    act(() => result.current.drafts.clearDrafts());
    expect(result.current.drafts.hasDrafts).toBe(false);
  });

  it("multiple drafts for different cells are tracked independently", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    act(() => {
      result.current.drafts.stageDraft({
        entryIndex: 0,
        outcomeId: "o1",
        probability: 0.7,
        context: [],
        previousProbability: 0.5,
      });
    });
    act(() => {
      result.current.drafts.stageDraft({
        entryIndex: 1,
        outcomeId: "o2",
        probability: 0.3,
        context: [],
        previousProbability: 0.4,
      });
    });
    expect(result.current.drafts.getDraft(0, "o1")).toBe(0.7);
    expect(result.current.drafts.getDraft(1, "o2")).toBe(0.3);
    expect(result.current.drafts.allDrafts()).toHaveLength(2);
  });

  it("works without HistoryProvider (no-op history)", () => {
    const { result } = renderHook(() => useDraftEdits());
    act(() => {
      result.current.stageDraft({
        entryIndex: 0,
        outcomeId: "o1",
        probability: 0.7,
        context: [],
        previousProbability: 0.5,
      });
    });
    expect(result.current.getDraft(0, "o1")).toBe(0.7);
  });
});
