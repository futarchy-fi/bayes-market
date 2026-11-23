import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders, createMockQueryResult } from "./helpers";
import Leaderboard from "@/routes/Leaderboard";

vi.mock("@/lib/exchange/hooks", () => ({
  useLeaderboard: vi.fn(),
}));

import { useLeaderboard } from "@/lib/exchange/hooks";
const mockUseLeaderboard = vi.mocked(useLeaderboard);

describe("Leaderboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("formats credit totals with fixed 2-decimal precision and eliminates float tail noise", () => {
    mockUseLeaderboard.mockReturnValue(
      createMockQueryResult({
        data: {
          entries: [
            { login: "alice", accountId: 1, total: "1000" },
            { login: null, accountId: 18, total: "80.00000000000000000000000002" },
            { login: "bob", accountId: 2, total: "0" },
          ],
        },
        isSuccess: true,
      }) as ReturnType<typeof useLeaderboard>,
    );

    renderWithProviders(<Leaderboard />);

    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("1,000.00")).toBeInTheDocument();
    expect(screen.getByText("Account #18")).toBeInTheDocument();
    expect(screen.getByText("80.00")).toBeInTheDocument();
    expect(screen.queryByText(/80\.000000/)).not.toBeInTheDocument();
    expect(screen.getByText("0.00")).toBeInTheDocument();
  });
});
