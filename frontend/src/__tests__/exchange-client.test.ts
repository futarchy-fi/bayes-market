import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  EXCHANGE_API,
  ExchangeApiError,
  getMe,
  logoutExchange,
  onExchangeUnauthorized,
  previewNetEdit,
} from "@/lib/exchange/client";

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
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ stake: "12", before: 0.4, after: 0.6, b: "50" }),
    });
    const payload = { variableId: "v1", outcomeId: "yes", target: 0.6 };
    await previewNetEdit(payload, "secret");
    expect(mockFetch).toHaveBeenCalledWith(`${EXCHANGE_API}/v1/net/orders/preview`, expect.objectContaining({
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json", Authorization: "Bearer secret" },
    }));
  });

  it("turns HTML 502/503/403 edge errors into clean ExchangeApiError without SyntaxError", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 502,
      text: async () => "<html><body><h1>502 Bad Gateway</h1></body></html>",
    });

    const error = await getMe("secret").catch((caught) => caught);
    expect(error).toBeInstanceOf(ExchangeApiError);
    expect(error).toMatchObject({
      status: 502,
      code: "unknown_error",
      message: "Exchange request failed (502)",
    });
  });

  it("turns plain-text error bodies into clean ExchangeApiError", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 503,
      text: async () => "Service temporarily overloaded",
    });

    const error = await getMe("secret").catch((caught) => caught);
    expect(error).toBeInstanceOf(ExchangeApiError);
    expect(error).toMatchObject({
      status: 503,
      code: "unknown_error",
      message: "Service temporarily overloaded",
    });
  });

  it("produces invalid_response ExchangeApiError when a 200 body is unexpectedly non-JSON", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => "<html>captive portal</html>",
    });

    const error = await getMe("secret").catch((caught) => caught);
    expect(error).toBeInstanceOf(ExchangeApiError);
    expect(error).toMatchObject({ status: 200, code: "invalid_response" });
  });

  it("notifies unauthorized listeners on authenticated HTTP 401", async () => {
    const listener = vi.fn();
    const unsub = onExchangeUnauthorized(listener);
    try {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 401,
        text: async () => JSON.stringify({ error: { code: "invalid_api_key", message: "revoked" } }),
      });

      const error = await getMe("expired-key").catch((caught) => caught);
      expect(error).toBeInstanceOf(ExchangeApiError);
      expect(error).toMatchObject({ status: 401, code: "invalid_api_key" });
      expect(listener).toHaveBeenCalledWith("expired-key", error);
    } finally {
      unsub();
    }
  });

  it("logoutExchange posts to /v1/auth/logout and ignores network errors", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 204, text: async () => "" });
    await logoutExchange("tok-1");
    expect(mockFetch).toHaveBeenCalledWith(`${EXCHANGE_API}/v1/auth/logout`, {
      method: "POST",
      headers: { Authorization: "Bearer tok-1" },
    });

    mockFetch.mockRejectedValueOnce(new Error("network down"));
    await expect(logoutExchange("tok-1")).resolves.toBeUndefined();
  });
});
