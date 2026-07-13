import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";
import { EXCHANGE_MODE_KEY } from "@/lib/exchangeMode";

// Exchange mode is the production default since the apex swap; the legacy
// component suites exercise the paper-mode rendering path, so tests run
// opted-out unless a test sets the flag itself.
beforeEach(() => {
  window.localStorage.setItem(EXCHANGE_MODE_KEY, "0");
});
