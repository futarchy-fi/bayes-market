import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProbabilityBar } from "@/components/ui/ProbabilityBar";

const OUTCOME_COLORS = [
  "#22c55e", "#ef4444", "#3b82f6", "#eab308", "#a855f7",
  "#ec4899", "#14b8a6", "#f97316",
];

describe("ProbabilityBar", () => {
  it("renders with probability 0 — both outcomes at 0", () => {
    const outcomes = [
      { id: "yes", name: "Yes" },
      { id: "no", name: "No" },
    ];
    const { container } = render(
      <ProbabilityBar outcomes={outcomes} marginals={{ yes: 0, no: 0 }} />,
    );

    // Title attributes show 0.0%
    expect(screen.getByTitle("Yes: 0.0%")).toBeInTheDocument();
    expect(screen.getByTitle("No: 0.0%")).toBeInTheDocument();

    // Visible span text shows 0.0%
    expect(screen.getByText("Yes 0.0%")).toBeInTheDocument();
    expect(screen.getByText("No 0.0%")).toBeInTheDocument();

    // Bar segments have 0% width and minWidth 0
    const bars = container.querySelectorAll("[title]");
    for (const bar of bars) {
      expect((bar as HTMLElement).style.width).toBe("0%");
      expect((bar as HTMLElement).style.minWidth).toBe("0");
    }
  });

  it("renders with probability 0.5 — both outcomes at 0.5", () => {
    const outcomes = [
      { id: "yes", name: "Yes" },
      { id: "no", name: "No" },
    ];
    render(
      <ProbabilityBar outcomes={outcomes} marginals={{ yes: 0.5, no: 0.5 }} />,
    );

    // Title attributes show 50.0%
    expect(screen.getByTitle("Yes: 50.0%")).toBeInTheDocument();
    expect(screen.getByTitle("No: 50.0%")).toBeInTheDocument();

    // Visible span text shows 50.0%
    expect(screen.getByText("Yes 50.0%")).toBeInTheDocument();
    expect(screen.getByText("No 50.0%")).toBeInTheDocument();

    // Bar segments have 50% width and minWidth 2 (since p > 0)
    const yesBar = screen.getByTitle("Yes: 50.0%");
    const noBar = screen.getByTitle("No: 50.0%");
    expect(yesBar.style.width).toBe("50%");
    expect(yesBar.style.minWidth).toBe("2px");
    expect(noBar.style.width).toBe("50%");
    expect(noBar.style.minWidth).toBe("2px");
  });

  it("renders with probability 1 — one outcome at 1, other at 0", () => {
    const outcomes = [
      { id: "yes", name: "Yes" },
      { id: "no", name: "No" },
    ];
    render(
      <ProbabilityBar outcomes={outcomes} marginals={{ yes: 1, no: 0 }} />,
    );

    // Title attributes
    expect(screen.getByTitle("Yes: 100.0%")).toBeInTheDocument();
    expect(screen.getByTitle("No: 0.0%")).toBeInTheDocument();

    // Visible span text
    expect(screen.getByText("Yes 100.0%")).toBeInTheDocument();
    expect(screen.getByText("No 0.0%")).toBeInTheDocument();

    // Bar widths
    const yesBar = screen.getByTitle("Yes: 100.0%");
    const noBar = screen.getByTitle("No: 0.0%");
    expect(yesBar.style.width).toBe("100%");
    expect(noBar.style.width).toBe("0%");
    expect(yesBar.style.minWidth).toBe("2px");
    expect(noBar.style.minWidth).toBe("0");
  });

  it("displays percentage in both title attributes and visible span labels", () => {
    const outcomes = [
      { id: "a", name: "Alpha" },
      { id: "b", name: "Beta" },
    ];
    const marginals = { a: 0.73, b: 0.27 };
    render(<ProbabilityBar outcomes={outcomes} marginals={marginals} />);

    // Title attributes (on the bar segments)
    expect(screen.getByTitle("Alpha: 73.0%")).toBeInTheDocument();
    expect(screen.getByTitle("Beta: 27.0%")).toBeInTheDocument();

    // Visible span labels (in the legend)
    expect(screen.getByText("Alpha 73.0%")).toBeInTheDocument();
    expect(screen.getByText("Beta 27.0%")).toBeInTheDocument();
  });

  it("applies correct bar width styling via inline styles", () => {
    const outcomes = [
      { id: "a", name: "A" },
      { id: "b", name: "B" },
      { id: "c", name: "C" },
    ];
    const marginals = { a: 0.2, b: 0.5, c: 0.3 };
    render(<ProbabilityBar outcomes={outcomes} marginals={marginals} />);

    const barA = screen.getByTitle("A: 20.0%");
    const barB = screen.getByTitle("B: 50.0%");
    const barC = screen.getByTitle("C: 30.0%");

    expect(barA.style.width).toBe("20%");
    expect(barB.style.width).toBe("50%");
    expect(barC.style.width).toBe("30%");

    // All have p > 0, so minWidth should be 2
    expect(barA.style.minWidth).toBe("2px");
    expect(barB.style.minWidth).toBe("2px");
    expect(barC.style.minWidth).toBe("2px");

    // Transition is set
    expect(barA.style.transition).toBe("width 0.3s ease");
  });

  it("multi-outcome color cycling wraps at OUTCOME_COLORS.length", () => {
    // Create more outcomes than colors to test wrapping
    const count = OUTCOME_COLORS.length + 2; // 10 outcomes, 8 colors
    const outcomes = Array.from({ length: count }, (_, i) => ({
      id: `o${i}`,
      name: `Outcome${i}`,
    }));
    const marginals = Object.fromEntries(
      outcomes.map((o) => [o.id, 1 / count]),
    );

    const { container } = render(
      <ProbabilityBar outcomes={outcomes} marginals={marginals} />,
    );

    // Get bar segments (divs with title attributes inside the bar container)
    const bars = container.querySelectorAll("[title]");
    expect(bars.length).toBe(count);

    // Verify colors wrap: outcome at index 8 should have same color as index 0
    const colorOf = (el: Element) => (el as HTMLElement).style.background;
    expect(colorOf(bars[0]!)).toBeTruthy();
    expect(colorOf(bars[OUTCOME_COLORS.length]!)).toBe(colorOf(bars[0]!));
    expect(colorOf(bars[OUTCOME_COLORS.length + 1]!)).toBe(colorOf(bars[1]!));

    // Verify legend spans also use wrapped colors
    const spans = container.querySelectorAll("span");
    expect(spans.length).toBe(count);
    const spanColor = (el: Element) => (el as HTMLElement).style.color;
    expect(spanColor(spans[0]!)).toBeTruthy();
    expect(spanColor(spans[OUTCOME_COLORS.length]!)).toBe(spanColor(spans[0]!));
  });
});
