import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProbabilityBar } from "@/components/ui/ProbabilityBar";
import { Spinner, LoadingPage, ErrorMessage } from "@/components/ui/Spinner";
import { StatusBadge } from "@/components/ui/StatusBadge";

describe("ProbabilityBar", () => {
  const outcomes = [
    { id: "yes", name: "Yes" },
    { id: "no", name: "No" },
  ];
  const marginals: Record<string, number> = { yes: 0.65, no: 0.35 };

  it("renders outcome names and formatted probabilities", () => {
    render(<ProbabilityBar outcomes={outcomes} marginals={marginals} />);
    expect(screen.getByText(/Yes/)).toBeInTheDocument();
    expect(screen.getByText(/65\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/No/)).toBeInTheDocument();
    expect(screen.getByText(/35\.0%/)).toBeInTheDocument();
  });

  it("uses title attributes with name: probability format", () => {
    render(<ProbabilityBar outcomes={outcomes} marginals={marginals} />);
    expect(screen.getByTitle("Yes: 65.0%")).toBeInTheDocument();
    expect(screen.getByTitle("No: 35.0%")).toBeInTheDocument();
  });

  it("missing marginal entries default to 0%", () => {
    render(<ProbabilityBar outcomes={outcomes} marginals={{}} />);
    expect(screen.getByTitle("Yes: 0.0%")).toBeInTheDocument();
    expect(screen.getByTitle("No: 0.0%")).toBeInTheDocument();
    expect(screen.getByText(/Yes 0\.0%/)).toBeInTheDocument();
  });

  it("empty outcomes array renders without crashing", () => {
    const { container } = render(<ProbabilityBar outcomes={[]} marginals={{}} />);
    expect(container).toBeTruthy();
  });
});

describe("Spinner", () => {
  it("renders an SVG element", () => {
    const { container } = render(<Spinner />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });

  it("default size is 24x24", () => {
    const { container } = render(<Spinner />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("24");
    expect(svg.getAttribute("height")).toBe("24");
  });

  it("custom size prop controls width/height attributes", () => {
    const { container } = render(<Spinner size={48} />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("48");
    expect(svg.getAttribute("height")).toBe("48");
  });
});

describe("LoadingPage", () => {
  it("renders a Spinner with size 32", () => {
    const { container } = render(<LoadingPage />);
    const svg = container.querySelector("svg")!;
    expect(svg).toBeInTheDocument();
    expect(svg.getAttribute("width")).toBe("32");
    expect(svg.getAttribute("height")).toBe("32");
  });
});

describe("ErrorMessage", () => {
  it("renders the provided message text", () => {
    render(<ErrorMessage message="Something broke" />);
    expect(screen.getByText("Something broke")).toBeInTheDocument();
  });

  it("has danger-colored styling", () => {
    render(<ErrorMessage message="fail" />);
    const el = screen.getByText("fail");
    expect(el.style.color).toBe("var(--color-danger)");
  });
});

describe("StatusBadge", () => {
  it("renders status text", () => {
    render(<StatusBadge status="active" />);
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  it("different statuses produce different border colors", () => {
    const { rerender } = render(<StatusBadge status="active" />);
    const activeEl = screen.getByText("active");
    const activeBorder = activeEl.style.border;

    rerender(<StatusBadge status="resolved" />);
    const resolvedEl = screen.getByText("resolved");
    const resolvedBorder = resolvedEl.style.border;

    expect(activeBorder).not.toBe(resolvedBorder);
    expect(activeBorder).toContain("var(--color-active)");
    expect(resolvedBorder).toContain("var(--color-resolved)");
  });

  it("text is in original case in DOM (CSS handles uppercase)", () => {
    render(<StatusBadge status="active" />);
    const el = screen.getByText("active");
    expect(el.textContent).toBe("active");
    expect(el.style.textTransform).toBe("uppercase");
  });
});
