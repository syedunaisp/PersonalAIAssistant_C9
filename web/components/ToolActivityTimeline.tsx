import ApprovalNotice from "@/components/ApprovalNotice";
import ToolActivityItem from "@/components/ToolActivityItem";
import type { DecideApproval, TurnActivity } from "@/lib/toolActivity";

type ToolActivityTimelineProps = {
  entries: TurnActivity[];
  onDecide?: DecideApproval;
  decidingId?: string | null;
};

export default function ToolActivityTimeline({
  entries,
  onDecide,
  decidingId = null,
}: ToolActivityTimelineProps) {
  if (entries.length === 0) return null;
  return (
    <ol
      aria-label="Tool activity"
      className="flex w-full max-w-[85%] flex-col gap-1.5 self-start sm:max-w-[75%]"
    >
      {entries.map((entry, index) => (
        <li key={entry.id} className="relative">
          {index > 0 && (
            <span
              aria-hidden="true"
              className="absolute -top-1.5 left-[17px] h-1.5 w-px bg-border-subtle"
            />
          )}
          {entry.kind === "tool" ? (
            <ToolActivityItem entry={entry} />
          ) : (
            <ApprovalNotice
              request={entry}
              onDecide={onDecide}
              deciding={decidingId === entry.pendingActionId}
            />
          )}
        </li>
      ))}
    </ol>
  );
}
