import { describe, expect, it } from "vitest";
import { queryKeys } from "@/lib/query/hooks";

describe("queryKeys.markets", () => {
  it("normalizes default, all-status, and trimmed search values", () => {
    expect(queryKeys.markets({ status: "all", sort: "volume", q: "  ETH  " })).toEqual([
      "markets",
      "list",
      { status: null, sort: "volume", q: "ETH" },
    ]);
  });

  it("changes when status, sort, or search changes", () => {
    expect(queryKeys.markets({ status: "active" })).not.toEqual(
      queryKeys.markets({ status: "resolved" }),
    );
    expect(queryKeys.markets({ sort: "liquidity" })).not.toEqual(
      queryKeys.markets({ sort: "created" }),
    );
    expect(queryKeys.markets({ q: "btc" })).not.toEqual(queryKeys.markets({ q: "eth" }));
  });
});
