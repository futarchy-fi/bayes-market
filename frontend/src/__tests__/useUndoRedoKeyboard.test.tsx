import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { HistoryProvider, useHistory } from "@/features/history/HistoryContext";
import { useUndoRedoKeyboard, isEditableElement } from "@/features/history/useUndoRedoKeyboard";
import type { Command } from "@/features/history/commands";
import type { ReactNode } from "react";

function makeCommand(desc = "test"): Command {
  return {
    description: desc,
    execute: vi.fn(),
    undo: vi.fn(),
  };
}

function wrapper({ children }: { children: ReactNode }) {
  return <HistoryProvider>{children}</HistoryProvider>;
}

function useTestHook() {
  const history = useHistory();
  useUndoRedoKeyboard();
  return history;
}

function fireKey(opts: { key: string; ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean }) {
  const event = new KeyboardEvent("keydown", {
    key: opts.key,
    ctrlKey: opts.ctrlKey ?? false,
    metaKey: opts.metaKey ?? false,
    shiftKey: opts.shiftKey ?? false,
    bubbles: true,
    cancelable: true,
  });
  document.dispatchEvent(event);
  return event;
}

describe("isEditableElement", () => {
  it("returns false for null", () => {
    expect(isEditableElement(null)).toBe(false);
  });

  it("returns true for INPUT element", () => {
    const el = document.createElement("input");
    expect(isEditableElement(el)).toBe(true);
  });

  it("returns true for TEXTAREA element", () => {
    const el = document.createElement("textarea");
    expect(isEditableElement(el)).toBe(true);
  });

  it("returns true for SELECT element", () => {
    const el = document.createElement("select");
    expect(isEditableElement(el)).toBe(true);
  });

  it("returns true for contenteditable element", () => {
    const el = document.createElement("div");
    el.contentEditable = "true";
    expect(isEditableElement(el)).toBe(true);
  });

  it("returns false for a regular div", () => {
    const el = document.createElement("div");
    expect(isEditableElement(el)).toBe(false);
  });

  it("returns false for a button", () => {
    const el = document.createElement("button");
    expect(isEditableElement(el)).toBe(false);
  });
});

describe("useUndoRedoKeyboard", () => {
  it("Ctrl+Z triggers undo when history has items", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    const cmd = makeCommand();
    act(() => result.current.push(cmd));
    act(() => fireKey({ key: "z", ctrlKey: true }));
    expect(cmd.undo).toHaveBeenCalled();
  });

  it("Ctrl+Shift+Z triggers redo", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    const cmd = makeCommand();
    act(() => result.current.push(cmd));
    act(() => result.current.undo());
    act(() => fireKey({ key: "z", ctrlKey: true, shiftKey: true }));
    expect(cmd.execute).toHaveBeenCalled();
  });

  it("Ctrl+Y triggers redo", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    const cmd = makeCommand();
    act(() => result.current.push(cmd));
    act(() => result.current.undo());
    act(() => fireKey({ key: "y", ctrlKey: true }));
    expect(cmd.execute).toHaveBeenCalled();
  });

  it("Meta+Z triggers undo (Mac)", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    const cmd = makeCommand();
    act(() => result.current.push(cmd));
    act(() => fireKey({ key: "z", metaKey: true }));
    expect(cmd.undo).toHaveBeenCalled();
  });

  it("does not trigger undo without Ctrl/Meta", () => {
    const { result } = renderHook(() => useTestHook(), { wrapper });
    const cmd = makeCommand();
    act(() => result.current.push(cmd));
    act(() => fireKey({ key: "z" }));
    expect(cmd.undo).not.toHaveBeenCalled();
  });

  it("does not trigger when activeElement is an input", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();

    const { result } = renderHook(() => useTestHook(), { wrapper });
    const cmd = makeCommand();
    act(() => result.current.push(cmd));
    act(() => fireKey({ key: "z", ctrlKey: true }));
    expect(cmd.undo).not.toHaveBeenCalled();

    document.body.removeChild(input);
  });

  it("does not trigger when activeElement is a textarea", () => {
    const textarea = document.createElement("textarea");
    document.body.appendChild(textarea);
    textarea.focus();

    const { result } = renderHook(() => useTestHook(), { wrapper });
    const cmd = makeCommand();
    act(() => result.current.push(cmd));
    act(() => fireKey({ key: "z", ctrlKey: true }));
    expect(cmd.undo).not.toHaveBeenCalled();

    document.body.removeChild(textarea);
  });
});
