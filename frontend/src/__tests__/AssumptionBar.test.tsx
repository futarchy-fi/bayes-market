import { describe, it, expect } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { AssumptionBar } from "@/features/assumptions/AssumptionBar";
import {
  AssumptionProvider,
  useAssumptions,
} from "@/features/assumptions/AssumptionContext";
import { renderWithProviders } from "./helpers";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const singleAssumption = [
  { variableId: "var-rain", outcomeId: "out-yes", label: "Rain" },
];

const multipleAssumptions = [
  { variableId: "var-rain", outcomeId: "out-yes", label: "Rain" },
  { variableId: "var-wind", outcomeId: "out-high", label: "Wind" },
  { variableId: "var-temp", outcomeId: "out-hot", label: "Temperature" },
];

// ---------------------------------------------------------------------------
// Seeder — identical pattern to AssumptionPanel.test.tsx
// ---------------------------------------------------------------------------

function Seeder({
  assumptions,
}: {
  assumptions: Array<{
    variableId: string;
    outcomeId: string;
    label: string;
  }>;
}) {
  const { addAssumption } = useAssumptions();
  return (
    <button
      data-testid="seed-assumptions"
      onClick={() => assumptions.forEach((a) => addAssumption(a))}
      style={{ display: "none" }}
    />
  );
}

function seedAssumptions() {
  fireEvent.click(screen.getByTestId("seed-assumptions"));
}

// ---------------------------------------------------------------------------
// Render helper
// ---------------------------------------------------------------------------

function renderBar(
  {
    initialAssumptions = [] as Array<{
      variableId: string;
      outcomeId: string;
      label: string;
    }>,
  } = {},
) {
  function Wrapper() {
    return (
      <AssumptionProvider>
        <Seeder assumptions={initialAssumptions} />
        <AssumptionBar />
      </AssumptionProvider>
    );
  }

  const result = renderWithProviders(<Wrapper />);

  if (initialAssumptions.length > 0) {
    seedAssumptions();
  }

  return result;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AssumptionBar", () => {
  // Step 4: bar is hidden when no assumptions
  describe("when there are no assumptions", () => {
    it("does not render", () => {
      renderBar();
      // The component returns null, so no bar content should exist
      expect(screen.queryByText("GIVEN:")).not.toBeInTheDocument();
      expect(screen.queryByText("Clear all")).not.toBeInTheDocument();
    });
  });

  // Step 2: renders assumption text in 'label = outcomeId' format
  describe("assumption text rendering", () => {
    it("renders each assumption as 'label = outcomeId'", () => {
      renderBar({ initialAssumptions: multipleAssumptions });

      expect(screen.getByText(/Rain = out-yes/)).toBeInTheDocument();
      expect(screen.getByText(/Wind = out-high/)).toBeInTheDocument();
      expect(screen.getByText(/Temperature = out-hot/)).toBeInTheDocument();
    });
  });

  // Step 3: renders GIVEN: label when assumptions are present
  describe("GIVEN: label", () => {
    it("renders GIVEN: when assumptions are present", () => {
      renderBar({ initialAssumptions: singleAssumption });

      expect(screen.getByText("GIVEN:")).toBeInTheDocument();
    });
  });

  // Step 5: remove button click removes individual assumption
  describe("individual assumption removal", () => {
    it("removes a single assumption when its remove button is clicked", () => {
      renderBar({ initialAssumptions: multipleAssumptions });

      // All three should be present initially
      expect(screen.getByText(/Rain = out-yes/)).toBeInTheDocument();
      expect(screen.getByText(/Wind = out-high/)).toBeInTheDocument();
      expect(screen.getByText(/Temperature = out-hot/)).toBeInTheDocument();

      // Click remove on "Wind"
      const removeWindBtn = screen.getByRole("button", {
        name: "Remove assumption Wind",
      });
      fireEvent.click(removeWindBtn);

      // Wind should be gone, others remain
      expect(screen.queryByText(/Wind = out-high/)).not.toBeInTheDocument();
      expect(screen.getByText(/Rain = out-yes/)).toBeInTheDocument();
      expect(screen.getByText(/Temperature = out-hot/)).toBeInTheDocument();
    });

    it("has correct aria-label on each remove button", () => {
      renderBar({ initialAssumptions: multipleAssumptions });

      expect(
        screen.getByRole("button", { name: "Remove assumption Rain" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Remove assumption Wind" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Remove assumption Temperature" }),
      ).toBeInTheDocument();
    });
  });

  // Step 6: Clear all button removes all assumptions
  describe("clear all", () => {
    it("removes all assumptions when Clear all is clicked", () => {
      renderBar({ initialAssumptions: multipleAssumptions });

      expect(screen.getByText("GIVEN:")).toBeInTheDocument();

      fireEvent.click(screen.getByText("Clear all"));

      // Bar should disappear entirely (returns null)
      expect(screen.queryByText("GIVEN:")).not.toBeInTheDocument();
      expect(screen.queryByText("Clear all")).not.toBeInTheDocument();
      expect(screen.queryByText(/Rain/)).not.toBeInTheDocument();
    });
  });

  // Step 7: multiple assumptions render as separate tags
  describe("multiple assumptions", () => {
    it("renders each assumption as a separate tag element", () => {
      renderBar({ initialAssumptions: multipleAssumptions });

      // Each assumption should have its own remove button, indicating separate tags
      const removeButtons = screen.getAllByRole("button", {
        name: /Remove assumption/,
      });
      expect(removeButtons).toHaveLength(3);

      // Each tag text is distinct
      expect(screen.getByText(/Rain = out-yes/)).toBeInTheDocument();
      expect(screen.getByText(/Wind = out-high/)).toBeInTheDocument();
      expect(screen.getByText(/Temperature = out-hot/)).toBeInTheDocument();
    });
  });

  // Step 8: structural styling — flex layout and tag structure
  describe("structural styling", () => {
    it("bar container uses flex display", () => {
      renderBar({ initialAssumptions: singleAssumption });

      // The bar container is the parent of the GIVEN: label
      const givenLabel = screen.getByText("GIVEN:");
      const barContainer = givenLabel.parentElement!;
      expect(barContainer.style.display).toBe("flex");
    });

    it("tag container uses flex display with wrapping", () => {
      renderBar({ initialAssumptions: multipleAssumptions });

      // The tag container wraps the assumption tags — it's the flex div between GIVEN: and Clear all
      const givenLabel = screen.getByText("GIVEN:");
      const barContainer = givenLabel.parentElement!;
      // The tag container is the second child (after GIVEN: span)
      const tagContainer = barContainer.children[1] as HTMLElement;
      expect(tagContainer.style.display).toBe("flex");
      expect(tagContainer.style.flexWrap).toBe("wrap");
    });

    it("each tag uses inline-flex display", () => {
      renderBar({ initialAssumptions: singleAssumption });

      // The tag is the span containing the assumption text
      const tagText = screen.getByText(/Rain = out-yes/);
      expect(tagText.style.display).toBe("inline-flex");
    });

    it("Clear all button is present and clickable", () => {
      renderBar({ initialAssumptions: singleAssumption });

      const clearBtn = screen.getByText("Clear all");
      expect(clearBtn.tagName).toBe("BUTTON");
    });
  });
});
