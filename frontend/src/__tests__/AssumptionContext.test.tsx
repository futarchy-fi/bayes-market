import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { ReactNode } from "react";
import {
  AssumptionProvider,
  useAssumptions,
  type Assumption,
} from "@/features/assumptions/AssumptionContext";

const wrapper = ({ children }: { children: ReactNode }) => (
  <AssumptionProvider>{children}</AssumptionProvider>
);

const assumption1: Assumption = { variableId: "v1", outcomeId: "o1", label: "Yes" };
const assumption2: Assumption = { variableId: "v2", outcomeId: "o2", label: "No" };

describe("useAssumptions", () => {
  it("starts with empty assumptions", () => {
    const { result } = renderHook(() => useAssumptions(), { wrapper });
    expect(result.current.assumptions).toEqual([]);
    expect(result.current.contextPayload).toEqual([]);
  });

  it("addAssumption adds to the list", () => {
    const { result } = renderHook(() => useAssumptions(), { wrapper });
    act(() => result.current.addAssumption(assumption1));
    expect(result.current.assumptions).toEqual([assumption1]);
  });

  it("addAssumption deduplicates by variableId", () => {
    const { result } = renderHook(() => useAssumptions(), { wrapper });
    act(() => result.current.addAssumption(assumption1));
    const updated: Assumption = { variableId: "v1", outcomeId: "o3", label: "Maybe" };
    act(() => result.current.addAssumption(updated));
    expect(result.current.assumptions).toEqual([updated]);
  });

  it("removeAssumption removes by variableId", () => {
    const { result } = renderHook(() => useAssumptions(), { wrapper });
    act(() => result.current.addAssumption(assumption1));
    act(() => result.current.addAssumption(assumption2));
    act(() => result.current.removeAssumption("v1"));
    expect(result.current.assumptions).toEqual([assumption2]);
  });

  it("clearAll empties the list", () => {
    const { result } = renderHook(() => useAssumptions(), { wrapper });
    act(() => result.current.addAssumption(assumption1));
    act(() => result.current.addAssumption(assumption2));
    act(() => result.current.clearAll());
    expect(result.current.assumptions).toEqual([]);
  });

  it("hasAssumption returns true/false", () => {
    const { result } = renderHook(() => useAssumptions(), { wrapper });
    act(() => result.current.addAssumption(assumption1));
    expect(result.current.hasAssumption("v1")).toBe(true);
    expect(result.current.hasAssumption("v2")).toBe(false);
  });

  it("getAssumption returns matching or undefined", () => {
    const { result } = renderHook(() => useAssumptions(), { wrapper });
    act(() => result.current.addAssumption(assumption1));
    expect(result.current.getAssumption("v1")).toEqual(assumption1);
    expect(result.current.getAssumption("v999")).toBeUndefined();
  });

  it("contextPayload strips label field", () => {
    const { result } = renderHook(() => useAssumptions(), { wrapper });
    act(() => result.current.addAssumption(assumption1));
    act(() => result.current.addAssumption(assumption2));
    expect(result.current.contextPayload).toEqual([
      { variableId: "v1", outcomeId: "o1" },
      { variableId: "v2", outcomeId: "o2" },
    ]);
  });

  it("throws when used outside AssumptionProvider", () => {
    expect(() => renderHook(() => useAssumptions())).toThrow(
      "useAssumptions must be used within AssumptionProvider",
    );
  });
});
