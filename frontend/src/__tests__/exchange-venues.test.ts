import { describe, expect, it } from "vitest";
import { instrumentPriceChips, validateBookOrder } from "@/lib/exchange/venues";

describe("instrumentPriceChips", () => {
  it("extracts venue prices and preserves an empty book", () => {
    expect(instrumentPriceChips({
      instrumentId: "ship-it",
      title: "Will it ship?",
      listings: [
        { venue: "net", marketId: "net-1", yesPrice: 0.61, status: "active" },
        { venue: "amm", marketId: "2", yesPrice: 0.625, status: "open" },
        { venue: "book", marketId: "3", yesPrice: null, status: "open" },
      ],
    })).toEqual([
      { venue: "net", price: "61.0%" },
      { venue: "amm", price: "62.5%" },
      { venue: "book", price: "—" },
    ]);
  });
});

describe("validateBookOrder", () => {
  it.each(["0", "1", "-0.1", "nope"])("rejects price %s outside (0, 1)", (price) => {
    expect(validateBookOrder(price, "1")).toBe("Price must be between 0 and 1.");
  });

  it.each(["0", "-1", "nope"])("rejects non-positive size %s", (size) => {
    expect(validateBookOrder("0.5", size)).toBe("Size must be greater than 0.");
  });

  it("accepts a valid limit order", () => {
    expect(validateBookOrder("0.5001", "1.25")).toBeNull();
  });
});
