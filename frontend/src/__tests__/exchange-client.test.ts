import { beforeEach, describe, expect, it, vi } from "vitest";
import { EXCHANGE_API, ExchangeApiError, getMe, previewNetEdit } from "@/lib/exchange/client";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("exchange client", () => {
  beforeEach(() => mockFetch.mockReset());

  it("maps the exchange error envelope and attaches auth", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ error: { code: "insufficient_credits", message: "not enough" } }),
    });

    const error = await getMe("secret").catch((caught) => caught);
    expect(error).toBeInstanceOf(ExchangeApiError);
    expect(error).toMatchObject({ status: 400, code: "insufficient_credits", message: "not enough" });
    expect(mockFetch).toHaveBeenCalledWith(`${EXCHANGE_API}/v1/me`, expect.objectContaining({
      headers: { Authorization: "Bearer secret" },
    }));
  });

  it("posts JSON edit payloads", async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ stake: "12", before: 0.4, after: 0.6, b: "50" }) });
    const payload = { variableId: "v1", outcomeId: "yes", target: 0.6 };
    await previewNetEdit(payload, "secret");
    expect(mockFetch).toHaveBeenCalledWith(`${EXCHANGE_API}/v1/net/orders/preview`, expect.objectContaining({
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json", Authorization: "Bearer secret" },
    }));
  });
});
