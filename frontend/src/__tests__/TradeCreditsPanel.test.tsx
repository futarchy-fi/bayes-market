import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StakePreview } from "@/lib/exchange/TradeCreditsPanel";

describe("StakePreview", () => {
  it("renders stake and before-to-after probabilities", () => {
    render(<StakePreview preview={{ stake: "17.25", before: 0.412, after: 0.7, b: "50" }} />);
    expect(screen.getByTestId("stake-preview")).toHaveTextContent("Stake to freeze: 17.25 credits · 41.2% → 70.0%");
  });
});
