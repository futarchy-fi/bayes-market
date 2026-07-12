import { describe, expect, it } from "vitest";
import { jointDistribution } from "@/features/compare/jointMath";

describe("jointDistribution", () => {
  it("derives joint statistics and handles degenerate marginals", () => {
    const result = jointDistribution(0.4, 0.7, 0.2);
    expect(result.p11).toBeCloseTo(0.28);
    expect(result.p10).toBeCloseTo(0.12);
    expect(result.p01).toBeCloseTo(0.12);
    expect(result.p00).toBeCloseTo(0.48);
    expect(result.pB).toBeCloseTo(0.4);
    expect(result.pAGivenB).toBeCloseTo(0.7);
    expect(result.pAGivenNotB).toBeCloseTo(0.2);
    expect(result.phi).toBeCloseTo(0.5);
    expect(result.mutualInformation).toBeCloseTo(0.185277);

    expect(jointDistribution(0, 1, 0).phi).toBe(0);
    expect(jointDistribution(1, 1, 0).phi).toBe(0);
    expect(jointDistribution(1, 1, 0).mutualInformation).toBe(0);
  });
});
