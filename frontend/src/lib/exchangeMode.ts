export const EXCHANGE_MODE_KEY = "exchange-mode";

/** Apply an explicit URL override, then read the persisted flag.

Exchange mode is the DEFAULT since the 2026-07-13 apex swap ("one
credits"). `?exchange=0` opts a browser back into the legacy paper
lane; `?exchange=1` clears the opt-out. */
export function resolveExchangeMode(search: string, storage: Storage): boolean {
  const override = new URLSearchParams(search).get("exchange");
  if (override === "1") storage.removeItem(EXCHANGE_MODE_KEY);
  if (override === "0") storage.setItem(EXCHANGE_MODE_KEY, "0");
  return storage.getItem(EXCHANGE_MODE_KEY) !== "0";
}

export function isExchangeMode(): boolean {
  return typeof window !== "undefined"
    && resolveExchangeMode(window.location.search, window.localStorage);
}
