import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { HistoryProvider, useHistory, HISTORY_CAP } from "@/features/history/HistoryContext";
import type { Command } from "@/features/history/commands";
import type { ReactNode } from "react";

function wrapper({ children }: { children: ReactNode }) {
  return <HistoryProvider>{children}</HistoryProvider>;
}

function makeCommand(desc = "test"): Command & { executeCalls: number; undoCalls: number } {
  const cmd = {
    description: desc,
    executeCalls: 0,
    undoCalls: 0,
    execute() { cmd.executeCalls++; },
    undo() { cmd.undoCalls++; },
  };
  return cmd;
}

describe("HistoryContext", () => {
  describe("initial state", () => {
    it("starts with empty stacks", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      expect(result.current.canUndo).toBe(false);
      expect(result.current.canRedo).toBe(false);
      expect(result.current.undoStack).toEqual([]);
      expect(result.current.redoStack).toEqual([]);
    });
  });

  describe("push", () => {
    it("adds a command to the undo stack", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      const cmd = makeCommand();
      act(() => result.current.push(cmd));
      expect(result.current.canUndo).toBe(true);
      expect(result.current.undoStack).toHaveLength(1);
    });

    it("clears the redo stack on push", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      const cmd1 = makeCommand("first");
      const cmd2 = makeCommand("second");
      act(() => result.current.push(cmd1));
      act(() => result.current.undo());
      expect(result.current.canRedo).toBe(true);
      act(() => result.current.push(cmd2));
      expect(result.current.canRedo).toBe(false);
      expect(result.current.redoStack).toEqual([]);
    });
  });

  describe("undo", () => {
    it("calls undo() on the most recent command", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      const cmd = makeCommand();
      act(() => result.current.push(cmd));
      act(() => result.current.undo());
      expect(cmd.undoCalls).toBe(1);
    });

    it("moves command from undo to redo stack", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      const cmd = makeCommand();
      act(() => result.current.push(cmd));
      act(() => result.current.undo());
      expect(result.current.canUndo).toBe(false);
      expect(result.current.canRedo).toBe(true);
      expect(result.current.redoStack).toHaveLength(1);
    });

    it("is a no-op when undo stack is empty", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      act(() => result.current.undo());
      expect(result.current.canUndo).toBe(false);
    });
  });

  describe("redo", () => {
    it("calls execute() on the most recently undone command", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      const cmd = makeCommand();
      act(() => result.current.push(cmd));
      act(() => result.current.undo());
      act(() => result.current.redo());
      expect(cmd.executeCalls).toBe(1);
    });

    it("moves command from redo to undo stack", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      const cmd = makeCommand();
      act(() => result.current.push(cmd));
      act(() => result.current.undo());
      act(() => result.current.redo());
      expect(result.current.canUndo).toBe(true);
      expect(result.current.canRedo).toBe(false);
    });

    it("is a no-op when redo stack is empty", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      act(() => result.current.redo());
      expect(result.current.canRedo).toBe(false);
    });
  });

  describe("clear", () => {
    it("empties both stacks", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      act(() => result.current.push(makeCommand()));
      act(() => result.current.push(makeCommand()));
      act(() => result.current.undo());
      act(() => result.current.clear());
      expect(result.current.canUndo).toBe(false);
      expect(result.current.canRedo).toBe(false);
    });
  });

  describe("cap at HISTORY_CAP", () => {
    it(`caps the undo stack at ${HISTORY_CAP}`, () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      for (let i = 0; i < HISTORY_CAP + 10; i++) {
        act(() => result.current.push(makeCommand(`cmd-${i}`)));
      }
      expect(result.current.undoStack).toHaveLength(HISTORY_CAP);
      // The oldest commands should have been evicted
      expect(result.current.undoStack[0]!.description).toBe("cmd-10");
    });
  });

  describe("multiple undo/redo cycle", () => {
    it("correctly sequences undo then redo across 3 commands", () => {
      const { result } = renderHook(() => useHistory(), { wrapper });
      const cmds = [makeCommand("a"), makeCommand("b"), makeCommand("c")];
      for (const c of cmds) act(() => result.current.push(c));

      // Undo all
      act(() => result.current.undo());
      expect(cmds[2]!.undoCalls).toBe(1);
      act(() => result.current.undo());
      expect(cmds[1]!.undoCalls).toBe(1);
      act(() => result.current.undo());
      expect(cmds[0]!.undoCalls).toBe(1);

      expect(result.current.canUndo).toBe(false);
      expect(result.current.redoStack).toHaveLength(3);

      // Redo first two
      act(() => result.current.redo());
      expect(cmds[0]!.executeCalls).toBe(1);
      act(() => result.current.redo());
      expect(cmds[1]!.executeCalls).toBe(1);

      expect(result.current.undoStack).toHaveLength(2);
      expect(result.current.redoStack).toHaveLength(1);
    });
  });

  describe("useHistory outside provider", () => {
    const originalError = console.error;
    beforeEach(() => { console.error = vi.fn(); });
    afterEach(() => { console.error = originalError; });

    it("throws when used outside HistoryProvider", () => {
      expect(() => renderHook(() => useHistory())).toThrow(
        "useHistory must be used within HistoryProvider",
      );
    });
  });
});
