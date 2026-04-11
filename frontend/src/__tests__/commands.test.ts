import { describe, it, expect, vi } from "vitest";
import {
  AssumptionAddCommand,
  AssumptionRemoveCommand,
  AssumptionClearAllCommand,
  ProbabilityEditCommand,
  type DraftEdit,
} from "@/features/history/commands";
import type { Assumption } from "@/features/assumptions/AssumptionContext";

describe("AssumptionAddCommand", () => {
  it("execute calls addAssumption", () => {
    const add = vi.fn();
    const remove = vi.fn();
    const assumption: Assumption = { variableId: "v1", outcomeId: "o1", label: "A" };
    const cmd = new AssumptionAddCommand({
      assumption,
      previousAssumption: undefined,
      addAssumption: add,
      removeAssumption: remove,
    });
    cmd.execute();
    expect(add).toHaveBeenCalledWith(assumption);
  });

  it("undo calls removeAssumption when no previous assumption existed", () => {
    const add = vi.fn();
    const remove = vi.fn();
    const assumption: Assumption = { variableId: "v1", outcomeId: "o1", label: "A" };
    const cmd = new AssumptionAddCommand({
      assumption,
      previousAssumption: undefined,
      addAssumption: add,
      removeAssumption: remove,
    });
    cmd.execute();
    cmd.undo();
    expect(remove).toHaveBeenCalledWith("v1");
  });

  it("undo restores previous assumption when one existed", () => {
    const add = vi.fn();
    const remove = vi.fn();
    const previous: Assumption = { variableId: "v1", outcomeId: "o0", label: "Old" };
    const current: Assumption = { variableId: "v1", outcomeId: "o1", label: "New" };
    const cmd = new AssumptionAddCommand({
      assumption: current,
      previousAssumption: previous,
      addAssumption: add,
      removeAssumption: remove,
    });
    cmd.execute();
    cmd.undo();
    expect(add).toHaveBeenCalledWith(previous);
    expect(remove).not.toHaveBeenCalled();
  });
});

describe("AssumptionRemoveCommand", () => {
  it("execute calls removeAssumption", () => {
    const add = vi.fn();
    const remove = vi.fn();
    const removed: Assumption = { variableId: "v1", outcomeId: "o1", label: "A" };
    const cmd = new AssumptionRemoveCommand({
      removedAssumption: removed,
      addAssumption: add,
      removeAssumption: remove,
    });
    cmd.execute();
    expect(remove).toHaveBeenCalledWith("v1");
  });

  it("undo calls addAssumption to restore", () => {
    const add = vi.fn();
    const remove = vi.fn();
    const removed: Assumption = { variableId: "v1", outcomeId: "o1", label: "A" };
    const cmd = new AssumptionRemoveCommand({
      removedAssumption: removed,
      addAssumption: add,
      removeAssumption: remove,
    });
    cmd.execute();
    cmd.undo();
    expect(add).toHaveBeenCalledWith(removed);
  });
});

describe("AssumptionClearAllCommand", () => {
  it("execute calls clearAll", () => {
    const setAll = vi.fn();
    const clear = vi.fn();
    const previous: Assumption[] = [
      { variableId: "v1", outcomeId: "o1", label: "A" },
      { variableId: "v2", outcomeId: "o2", label: "B" },
    ];
    const cmd = new AssumptionClearAllCommand({
      previousAssumptions: previous,
      setAllAssumptions: setAll,
      clearAll: clear,
    });
    cmd.execute();
    expect(clear).toHaveBeenCalled();
  });

  it("undo restores all previous assumptions", () => {
    const setAll = vi.fn();
    const clear = vi.fn();
    const previous: Assumption[] = [
      { variableId: "v1", outcomeId: "o1", label: "A" },
      { variableId: "v2", outcomeId: "o2", label: "B" },
    ];
    const cmd = new AssumptionClearAllCommand({
      previousAssumptions: previous,
      setAllAssumptions: setAll,
      clearAll: clear,
    });
    cmd.execute();
    cmd.undo();
    expect(setAll).toHaveBeenCalledWith(previous);
  });

  it("stores a snapshot of previousAssumptions (not a reference)", () => {
    const setAll = vi.fn();
    const clear = vi.fn();
    const previous: Assumption[] = [{ variableId: "v1", outcomeId: "o1", label: "A" }];
    const cmd = new AssumptionClearAllCommand({
      previousAssumptions: previous,
      setAllAssumptions: setAll,
      clearAll: clear,
    });
    // Mutate the source array after construction
    previous.push({ variableId: "v2", outcomeId: "o2", label: "B" });
    cmd.undo();
    // Should only have the original 1 element
    expect(setAll).toHaveBeenCalledWith([{ variableId: "v1", outcomeId: "o1", label: "A" }]);
  });
});

describe("ProbabilityEditCommand", () => {
  it("execute calls applyDrafts with the drafts", () => {
    const apply = vi.fn();
    const revert = vi.fn();
    const drafts: DraftEdit[] = [
      { entryIndex: 0, outcomeId: "o1", probability: 0.7, context: [], previousProbability: 0.5 },
    ];
    const cmd = new ProbabilityEditCommand({ drafts, applyDrafts: apply, revertDrafts: revert });
    cmd.execute();
    expect(apply).toHaveBeenCalledWith(drafts);
  });

  it("undo calls revertDrafts with the drafts", () => {
    const apply = vi.fn();
    const revert = vi.fn();
    const drafts: DraftEdit[] = [
      { entryIndex: 0, outcomeId: "o1", probability: 0.7, context: [], previousProbability: 0.5 },
    ];
    const cmd = new ProbabilityEditCommand({ drafts, applyDrafts: apply, revertDrafts: revert });
    cmd.execute();
    cmd.undo();
    expect(revert).toHaveBeenCalledWith(drafts);
  });

  it("uses custom description when provided", () => {
    const cmd = new ProbabilityEditCommand({
      drafts: [],
      applyDrafts: vi.fn(),
      revertDrafts: vi.fn(),
      description: "Custom desc",
    });
    expect(cmd.description).toBe("Custom desc");
  });

  it("generates default description from draft count", () => {
    const drafts: DraftEdit[] = [
      { entryIndex: 0, outcomeId: "o1", probability: 0.7, context: [], previousProbability: 0.5 },
      { entryIndex: 1, outcomeId: "o2", probability: 0.3, context: [], previousProbability: 0.4 },
    ];
    const cmd = new ProbabilityEditCommand({
      drafts,
      applyDrafts: vi.fn(),
      revertDrafts: vi.fn(),
    });
    expect(cmd.description).toBe("Edit 2 probability value(s)");
  });
});
