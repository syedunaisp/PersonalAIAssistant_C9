import { formatArgValue, truncateText, type ToolActivityEntry } from "@/lib/toolActivity";

const MAX_RESULT_LENGTH = 200;

const BADGE_STYLES = {
  neutral: "border-border-subtle bg-surface text-text-muted",
  warning: "border-warning bg-warning/10 text-text",
  danger: "border-danger bg-danger/10 text-text",
} as const;

function badgeFor(entry: ToolActivityEntry): { label: string; className: string } {
  if (entry.classification === "unknown" || !entry.listed) {
    return { label: "unknown tool", className: BADGE_STYLES.warning };
  }
  if (entry.classification === "destructive") {
    return { label: "destructive", className: BADGE_STYLES.danger };
  }
  if (entry.classification === "write") {
    return { label: "write", className: BADGE_STYLES.warning };
  }
  return { label: "read", className: BADGE_STYLES.neutral };
}

function StatusIcon({ status }: { status: ToolActivityEntry["status"] }) {
  if (status === "proposed") {
    return (
      <span role="img" aria-label="Running" className="shrink-0">
        <span className="block h-3 w-3 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      </span>
    );
  }
  if (status === "awaiting_approval") {
    return (
      <span
        role="img"
        aria-label="Awaiting approval"
        className="typing-dot h-2 w-2 shrink-0 rounded-full bg-warning"
      />
    );
  }
  const failed = status === "failed";
  return (
    <span
      role="img"
      aria-label={failed ? "Failed" : "Completed"}
      className={`shrink-0 ${failed ? "text-danger" : "text-accent"}`}
    >
      <svg
        viewBox="0 0 12 12"
        className="h-3 w-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        aria-hidden="true"
      >
        {failed ? (
          <path d="M2 2l8 8M10 2l-8 8" strokeLinecap="round" />
        ) : (
          <path d="M2 6.5l2.5 2.5L10 3.5" strokeLinecap="round" strokeLinejoin="round" />
        )}
      </svg>
    </span>
  );
}

type ToolActivityItemProps = { entry: ToolActivityEntry };

export default function ToolActivityItem({ entry }: ToolActivityItemProps) {
  const badge = badgeFor(entry);
  const argEntries = Object.entries(entry.args);
  return (
    <div className="rounded-input border border-border-subtle bg-surface-raised px-3 py-2 shadow-sm">
      <div className="flex items-center gap-2">
        <StatusIcon status={entry.status} />
        <span className="min-w-0 truncate text-xs font-semibold text-text">{entry.tool}</span>
        <span
          className={`ml-auto shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium leading-none ${badge.className}`}
        >
          {badge.label}
        </span>
      </div>
      {argEntries.length > 0 && (
        <dl className="mt-1.5 space-y-0.5 font-mono text-[11px] leading-snug text-text-muted">
          {argEntries.map(([key, value]) => (
            <div key={key} className="flex gap-1">
              <dt className="shrink-0">{key}:</dt>
              <dd className="min-w-0 break-words">{formatArgValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {entry.result && (
        <p
          className={`mt-1.5 border-t border-border-subtle pt-1.5 text-xs leading-snug ${
            entry.status === "failed" ? "text-danger" : "text-text-muted"
          }`}
        >
          {truncateText(entry.result, MAX_RESULT_LENGTH)}
        </p>
      )}
    </div>
  );
}
