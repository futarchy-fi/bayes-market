import { describe, expect, it } from "vitest";
import { parseExchangeFragment } from "@/lib/exchange/session";

describe("parseExchangeFragment", () => {
  it("reads the OAuth API key and decoded GitHub login", () => {
    expect(parseExchangeFragment("#auth=key%2Fwith%2Bsymbols&account_id=42&login=octo+cat")).toEqual({
      apiKey: "key/with+symbols",
      githubLogin: "octo cat",
    });
  });

  it("rejects a fragment without auth", () => {
    expect(parseExchangeFragment("#login=octocat")).toBeNull();
  });
});
