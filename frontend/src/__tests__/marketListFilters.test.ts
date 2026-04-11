import { describe, it, expect } from "vitest";
import {
  isMarketListStatusFilter,
  isMarketListSort,
  normalizeMarketListFilters,
  marketListQueryKey,
  marketListSearchParams,
  readMarketListFiltersFromSearchParams,
} from "@/lib/marketListFilters";

describe("isMarketListStatusFilter", () => {
  it("accepts 'all'", () => expect(isMarketListStatusFilter("all")).toBe(true));
  it("accepts 'active'", () => expect(isMarketListStatusFilter("active")).toBe(true));
  it("accepts 'resolved'", () => expect(isMarketListStatusFilter("resolved")).toBe(true));
  it("accepts 'closed'", () => expect(isMarketListStatusFilter("closed")).toBe(true));
  it("accepts 'draft'", () => expect(isMarketListStatusFilter("draft")).toBe(true));
  it("rejects invalid string", () => expect(isMarketListStatusFilter("bogus")).toBe(false));
  it("rejects empty string", () => expect(isMarketListStatusFilter("")).toBe(false));
  it("rejects null", () => expect(isMarketListStatusFilter(null)).toBe(false));
});

describe("isMarketListSort", () => {
  it("accepts 'volume'", () => expect(isMarketListSort("volume")).toBe(true));
  it("accepts 'liquidity'", () => expect(isMarketListSort("liquidity")).toBe(true));
  it("accepts 'created'", () => expect(isMarketListSort("created")).toBe(true));
  it("rejects invalid string", () => expect(isMarketListSort("bogus")).toBe(false));
  it("rejects empty string", () => expect(isMarketListSort("")).toBe(false));
  it("rejects null", () => expect(isMarketListSort(null)).toBe(false));
});

describe("normalizeMarketListFilters", () => {
  it("strips 'all' status", () => {
    expect(normalizeMarketListFilters({ status: "all" })).toEqual({});
  });
  it("keeps valid status", () => {
    expect(normalizeMarketListFilters({ status: "active" })).toEqual({ status: "active" });
  });
  it("keeps valid sort", () => {
    expect(normalizeMarketListFilters({ sort: "volume" })).toEqual({ sort: "volume" });
  });
  it("trims q whitespace", () => {
    expect(normalizeMarketListFilters({ q: "  hello  " })).toEqual({ q: "hello" });
  });
  it("drops empty q", () => {
    expect(normalizeMarketListFilters({ q: "" })).toEqual({});
  });
  it("drops whitespace-only q", () => {
    expect(normalizeMarketListFilters({ q: "   " })).toEqual({});
  });
  it("defaults to empty object", () => {
    expect(normalizeMarketListFilters()).toEqual({});
  });
  it("normalizes all fields together", () => {
    expect(normalizeMarketListFilters({ status: "resolved", sort: "created", q: " test " })).toEqual({
      status: "resolved",
      sort: "created",
      q: "test",
    });
  });
});

describe("marketListQueryKey", () => {
  it("returns nulls for empty input", () => {
    expect(marketListQueryKey()).toEqual({ status: null, sort: null, q: null });
  });
  it("returns nulls for 'all' status", () => {
    expect(marketListQueryKey({ status: "all" })).toEqual({ status: null, sort: null, q: null });
  });
  it("returns values for present fields", () => {
    expect(marketListQueryKey({ status: "active", sort: "volume", q: "foo" })).toEqual({
      status: "active",
      sort: "volume",
      q: "foo",
    });
  });
  it("mixes nulls and values", () => {
    expect(marketListQueryKey({ sort: "liquidity" })).toEqual({
      status: null,
      sort: "liquidity",
      q: null,
    });
  });
});

describe("marketListSearchParams", () => {
  it("encodes all normalized filters", () => {
    const params = marketListSearchParams({ status: "active", sort: "volume", q: "test" });
    expect(params.get("status")).toBe("active");
    expect(params.get("sort")).toBe("volume");
    expect(params.get("q")).toBe("test");
  });
  it("omits empty fields", () => {
    const params = marketListSearchParams({});
    expect(params.toString()).toBe("");
  });
  it("omits 'all' status", () => {
    const params = marketListSearchParams({ status: "all" });
    expect(params.has("status")).toBe(false);
  });
  it("trims q before encoding", () => {
    const params = marketListSearchParams({ q: "  hello  " });
    expect(params.get("q")).toBe("hello");
  });
});

describe("readMarketListFiltersFromSearchParams", () => {
  it("decodes valid params", () => {
    const params = new URLSearchParams("status=active&sort=volume&q=test");
    expect(readMarketListFiltersFromSearchParams(params)).toEqual({
      status: "active",
      sort: "volume",
      q: "test",
    });
  });
  it("ignores invalid status", () => {
    const params = new URLSearchParams("status=bogus&sort=volume");
    expect(readMarketListFiltersFromSearchParams(params)).toEqual({ sort: "volume" });
  });
  it("ignores invalid sort", () => {
    const params = new URLSearchParams("status=active&sort=bogus");
    expect(readMarketListFiltersFromSearchParams(params)).toEqual({ status: "active" });
  });
  it("handles missing params", () => {
    const params = new URLSearchParams("");
    expect(readMarketListFiltersFromSearchParams(params)).toEqual({});
  });
  it("trims q from search params", () => {
    const params = new URLSearchParams("q=%20hello%20");
    expect(readMarketListFiltersFromSearchParams(params)).toEqual({ q: "hello" });
  });
});

describe("round-trip: marketListSearchParams → readMarketListFiltersFromSearchParams", () => {
  it("round-trips all filters", () => {
    const input = { status: "active" as const, sort: "volume" as const, q: "test" };
    const params = marketListSearchParams(input);
    expect(readMarketListFiltersFromSearchParams(params)).toEqual({
      status: "active",
      sort: "volume",
      q: "test",
    });
  });
  it("round-trips empty/defaults", () => {
    const params = marketListSearchParams({});
    expect(readMarketListFiltersFromSearchParams(params)).toEqual({});
  });
  it("round-trips 'all' status (normalized away)", () => {
    const params = marketListSearchParams({ status: "all" });
    expect(readMarketListFiltersFromSearchParams(params)).toEqual({});
  });
});
