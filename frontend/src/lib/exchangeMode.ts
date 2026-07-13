export const EXCHANGE_MODE_KEY = "exchange-mode";

/** Apply an explicit URL override, then read the persisted dark-launch flag. */
export function resolveExchangeMode(search: string, storage: Storage): boolean {
  const override = new URLSearchParams(search).get("exchange");
  if (override === "1") storage.setItem(EXCHANGE_MODE_KEY, "1");
  if (override === "0") storage.removeItem(EXCHANGE_MODE_KEY);
  return storage.getItem(EXCHANGE_MODE_KEY) === "1";
}

export function isExchangeMode(): boolean {
  return typeof window !== "undefined"
    && resolveExchangeMode(window.location.search, window.localStorage);
}
