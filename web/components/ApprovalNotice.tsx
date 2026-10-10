"use client";

import { useState, type FormEvent } from "react";
import { formatArgValue, type ApprovalEntry, type DecideApproval } from "@/lib/toolActivity";

type ApprovalNoticeProps = {
  request: ApprovalEntry;
  /** Called on Approve/Reject/Edit; the hook owns the API call and state. */
  onDecide?: DecideApproval;
  /** True while the approve continuation is streaming. */
  deciding?: boolean;
};

/** Render one arg value for editing: arrays become comma-separated text. */
function argToInput(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value) ?? "";
  } catch {
    return "";
  }
}

/** Turn edited text back into a value: comma-split only for array-typed args. */
function inputToArg(raw: string, wasArray: boolean): unknown {
  if (wasArray) {
    return raw
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
  }
  return raw;
}

const INPUT_CLASS =
  "w-full rounded-input border border-border-subtle bg-surface px-2 py-1 font-mono text-[11px] text-text outline-none focus:border-accent";

export default function ApprovalNotice({ request, onDecide, deciding = false }: ApprovalNoticeProps) {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(request.args).map(([key, value]) => [key, argToInput(value)])),
  );

  const decided = request.decision !== undefined;
  const disabled = decided || deciding || !onDecide;
  const argEntries = Object.entries(request.args);

  const saveEdit = (event: FormEvent) => {
    event.preventDefault();
    if (!onDecide) return;
    const editedArgs = Object.fromEntries(
      Object.entries(values).map(([key, raw]) => [
        key,
        inputToArg(raw, Array.isArray(request.args[key])),
      ]),
    );
    onDecide(request.pendingActionId, "edit", editedArgs);
    setEditing(false);
  };

  return (
    <div className="rounded-input border border-warning bg-warning/10 px-3 py-2 shadow-sm">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold text-text">
          {request.decision === "rejected"
            ? "Rejected"
            : request.decision === "approved"
              ? request.decisionOutcome === "error"
                ? "Approval failed"
                : request.decisionOutcome === "done"
                  ? "Approved"
                  : "Executing…"
              : "Approval required"}
        </span>
        <span className="ml-auto shrink-0 rounded-full border border-warning bg-surface-raised px-2 py-0.5 text-[10px] font-medium leading-none text-text">
          {request.tool}
        </span>
      </div>

      {argEntries.length > 0 && !editing && (
        <dl className="mt-1.5 space-y-0.5 font-mono text-[11px] leading-snug text-text-muted">
          {argEntries.map(([key, value]) => (
            <div key={key} className="flex gap-1">
              <dt className="shrink-0">{key}:</dt>
              <dd className="min-w-0 break-words">{formatArgValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {editing && (
        <form onSubmit={saveEdit} className="mt-1.5 space-y-1.5">
          {argEntries.map(([key]) => (
            <label key={key} className="block">
              <span className="mb-0.5 block font-mono text-[10px] text-text-muted">{key}</span>
              <input
                value={values[key] ?? ""}
                onChange={(event) =>
                  setValues((prev) => ({ ...prev, [key]: event.target.value }))
                }
                className={INPUT_CLASS}
                autoComplete="off"
              />
            </label>
          ))}
          <div className="flex gap-1.5 pt-0.5">
            <button
              type="submit"
              className="rounded-input bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground"
            >
              Save
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-input border border-border-subtle bg-surface-raised px-2.5 py-1 text-xs font-medium text-text"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {!editing && (
        <p className="mt-1.5 text-xs text-text">
          This will use {request.estimatedCostTasks} of your remaining tasks.
        </p>
      )}

      {!decided && !editing && (
        <div className="mt-2 flex gap-1.5">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onDecide?.(request.pendingActionId, "approve")}
            className="rounded-input bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground disabled:opacity-50"
          >
            {deciding ? "Executing…" : "Approve"}
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onDecide?.(request.pendingActionId, "edit")}
            className="rounded-input border border-border-subtle bg-surface-raised px-2.5 py-1 text-xs font-medium text-text disabled:opacity-50"
          >
            Edit
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onDecide?.(request.pendingActionId, "reject")}
            className="ml-auto rounded-input border border-danger bg-danger/10 px-2.5 py-1 text-xs font-medium text-text disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      )}
    </div>
  );
}
