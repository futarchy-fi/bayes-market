import type { Assumption } from "@/features/assumptions/AssumptionContext";

/** Generic command interface for undo/redo operations */
export interface Command {
  /** Human-readable description of the action */
  readonly description: string;
  /** Execute the action */
  execute(): void;
  /** Reverse the action */
  undo(): void;
}

// ---------------------------------------------------------------------------
// Assumption commands
// ---------------------------------------------------------------------------

export class AssumptionAddCommand implements Command {
  readonly description: string;
  private readonly assumption: Assumption;
  private readonly previousAssumption: Assumption | undefined;
  private readonly doAdd: (a: Assumption) => void;
  private readonly doRemove: (variableId: string) => void;
  private readonly doAddBack: (a: Assumption) => void;

  constructor(opts: {
    assumption: Assumption;
    previousAssumption: Assumption | undefined;
    addAssumption: (a: Assumption) => void;
    removeAssumption: (variableId: string) => void;
  }) {
    this.assumption = opts.assumption;
    this.previousAssumption = opts.previousAssumption;
    this.doAdd = opts.addAssumption;
    this.doRemove = opts.removeAssumption;
    this.doAddBack = opts.addAssumption;
    this.description = `Assume ${opts.assumption.label} for ${opts.assumption.variableId}`;
  }

  execute() {
    this.doAdd(this.assumption);
  }

  undo() {
    if (this.previousAssumption) {
      this.doAddBack(this.previousAssumption);
    } else {
      this.doRemove(this.assumption.variableId);
    }
  }
}

export class AssumptionRemoveCommand implements Command {
  readonly description: string;
  private readonly removedAssumption: Assumption;
  private readonly doAdd: (a: Assumption) => void;
  private readonly doRemove: (variableId: string) => void;

  constructor(opts: {
    removedAssumption: Assumption;
    addAssumption: (a: Assumption) => void;
    removeAssumption: (variableId: string) => void;
  }) {
    this.removedAssumption = opts.removedAssumption;
    this.doAdd = opts.addAssumption;
    this.doRemove = opts.removeAssumption;
    this.description = `Remove assumption for ${opts.removedAssumption.variableId}`;
  }

  execute() {
    this.doRemove(this.removedAssumption.variableId);
  }

  undo() {
    this.doAdd(this.removedAssumption);
  }
}

export class AssumptionClearAllCommand implements Command {
  readonly description = "Clear all assumptions";
  private readonly previousAssumptions: Assumption[];
  private readonly doSetAll: (assumptions: Assumption[]) => void;
  private readonly doClear: () => void;

  constructor(opts: {
    previousAssumptions: Assumption[];
    setAllAssumptions: (assumptions: Assumption[]) => void;
    clearAll: () => void;
  }) {
    this.previousAssumptions = [...opts.previousAssumptions];
    this.doSetAll = opts.setAllAssumptions;
    this.doClear = opts.clearAll;
  }

  execute() {
    this.doClear();
  }

  undo() {
    this.doSetAll(this.previousAssumptions);
  }
}

// ---------------------------------------------------------------------------
// Probability edit draft commands
// ---------------------------------------------------------------------------

export interface DraftEdit {
  entryIndex: number;
  outcomeId: string;
  probability: number;
  context: Array<{ variableId: string; outcomeId: string }>;
  previousProbability: number;
  /** True if a draft already existed for this cell before this edit */
  hadPriorDraft?: boolean;
}

export class ProbabilityEditCommand implements Command {
  readonly description: string;
  private readonly drafts: DraftEdit[];
  private readonly applyDrafts: (drafts: DraftEdit[]) => void;
  private readonly revertDrafts: (drafts: DraftEdit[]) => void;

  constructor(opts: {
    drafts: DraftEdit[];
    applyDrafts: (drafts: DraftEdit[]) => void;
    revertDrafts: (drafts: DraftEdit[]) => void;
    description?: string;
  }) {
    this.drafts = opts.drafts;
    this.applyDrafts = opts.applyDrafts;
    this.revertDrafts = opts.revertDrafts;
    this.description = opts.description ?? `Edit ${opts.drafts.length} probability value(s)`;
  }

  execute() {
    this.applyDrafts(this.drafts);
  }

  undo() {
    this.revertDrafts(this.drafts);
  }
}
