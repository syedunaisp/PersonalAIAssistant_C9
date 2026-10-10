import type { FormEvent } from "react";

const INPUT =
  "h-11 min-w-0 flex-1 rounded-input border border-border-subtle bg-surface-raised px-3 text-sm text-text placeholder:text-text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
const SEND =
  "h-11 rounded-input bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors duration-150 hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50";
const STOP =
  "h-11 rounded-input border border-danger px-4 text-sm font-medium text-danger transition-colors duration-150 hover:bg-danger hover:text-danger-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

type ChatComposerProps = {
  draft: string;
  onDraftChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onStop: () => void;
  busy: boolean;
};

export default function ChatComposer({
  draft,
  onDraftChange,
  onSubmit,
  onStop,
  busy,
}: ChatComposerProps) {
  return (
    <form
      onSubmit={onSubmit}
      className="flex items-center gap-2 border-t border-border-subtle px-4 py-3 sm:px-6"
    >
      <label htmlFor="chat-input" className="sr-only">
        Message
      </label>
      <input
        id="chat-input"
        autoComplete="off"
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        placeholder="Type a message…"
        className={INPUT}
      />
      {busy ? (
        <button type="button" onClick={onStop} className={STOP}>
          Stop
        </button>
      ) : (
        <button type="submit" disabled={!draft.trim()} className={SEND}>
          Send
        </button>
      )}
    </form>
  );
}
