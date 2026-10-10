export type ToolClassification = "read" | "write" | "destructive";

export type ToolCallBase = {
  tool: string;
  classification: ToolClassification | "unknown";
  listed: boolean;
  args: Record<string, unknown>;
};

export type ToolResultData = { tool: string; result: string; ok: boolean };

export type ApprovalRequest = ToolCallBase & {
  estimatedCostTasks: number;
  pendingActionId: string;
};

export type DoneMeta = { stoppedForApproval: boolean };

export type ApprovalDecisionAction = "approve" | "reject" | "edit";

export type DecideApproval = (
  pendingActionId: string,
  action: ApprovalDecisionAction,
  editedArgs?: Record<string, unknown>,
) => void;

export type ToolActivityStatus = "proposed" | "awaiting_approval" | "done" | "failed";

export type ToolActivityEntry = ToolCallBase & {
  kind: "tool";
  id: string;
  status: ToolActivityStatus;
  result?: string;
};

export type ApprovalEntry = ApprovalRequest & {
  kind: "approval";
  id: string;
  /** Set once the user acts on the card; its buttons disable from then on. */
  decision?: "approved" | "rejected";
  /** Approve only: how the continuation stream ended. */
  decisionOutcome?: "done" | "error";
};

export type TurnActivity = ToolActivityEntry | ApprovalEntry;

export function toolEntry(proposal: ToolCallBase, id: string): ToolActivityEntry {
  return { kind: "tool", id, status: "proposed", ...proposal };
}

export function approvalEntry(request: ApprovalRequest, id: string): ApprovalEntry {
  return { kind: "approval", id, ...request };
}

function replaceAt<T>(items: T[], index: number, value: T): T[] {
  return [...items.slice(0, index), value, ...items.slice(index + 1)];
}

export function markAwaitingApproval(activity: TurnActivity[], tool: string): TurnActivity[] {
  for (let index = activity.length - 1; index >= 0; index--) {
    const entry = activity[index];
    if (entry.kind === "tool" && entry.tool === tool && entry.status === "proposed") {
      return replaceAt(activity, index, { ...entry, status: "awaiting_approval" });
    }
  }
  return activity;
}

export function updateToolResult(activity: TurnActivity[], result: ToolResultData): TurnActivity[] {
  for (let index = activity.length - 1; index >= 0; index--) {
    const entry = activity[index];
    const pending =
      entry.kind === "tool" &&
      entry.tool === result.tool &&
      (entry.status === "proposed" || entry.status === "awaiting_approval");
    if (pending) {
      const failed = !result.ok || result.result.startsWith("Error:");
      const updated: ToolActivityEntry = {
        ...entry,
        status: failed ? "failed" : "done",
        result: result.result,
      };
      return replaceAt(activity, index, updated);
    }
  }
  return activity;
}

/** Set the decision on the approval card with the given pending action id. */
export function updateApprovalDecision(
  activity: TurnActivity[],
  pendingActionId: string,
  decision: "approved" | "rejected",
): TurnActivity[] {
  return activity.map((entry) =>
    entry.kind === "approval" && entry.pendingActionId === pendingActionId
      ? { ...entry, decision }
      : entry,
  );
}

/** Replace the args shown on an approval card (edit flow). */
export function updateApprovalArgs(
  activity: TurnActivity[],
  pendingActionId: string,
  args: Record<string, unknown>,
): TurnActivity[] {
  return activity.map((entry) =>
    entry.kind === "approval" && entry.pendingActionId === pendingActionId
      ? { ...entry, args }
      : entry,
  );
}

const MAX_ARG_LENGTH = 80;

export function truncateText(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function formatArgValue(value: unknown): string {
  if (typeof value === "string") return truncateText(value, MAX_ARG_LENGTH);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return truncateText(JSON.stringify(value) ?? "null", MAX_ARG_LENGTH);
  } catch {
    return "[complex value]";
  }
}
