"use client";

import { Fragment, useEffect, useRef } from "react";
import ChatMessage from "@/components/ChatMessage";
import ChatComposer from "@/components/ChatComposer";
import StatusBanner from "@/components/StatusBanner";
import ToolActivityTimeline from "@/components/ToolActivityTimeline";
import { useChat } from "@/hooks/useChat";

export default function ChatPage() {
  const { messages, draft, setDraft, status, error, send, stop, dismissError, decide, decidingId } =
    useChat();
  const threadRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const thread = threadRef.current;
    if (thread) thread.scrollTop = thread.scrollHeight;
  }, [messages]);

  const busy = status !== "idle";
  const lastId = messages.length > 0 ? messages[messages.length - 1].id : null;
  const statusLabel =
    status === "idle" ? "Ready" : status === "loading" ? "Thinking…" : "Streaming…";

  return (
    <div className="mx-auto flex h-dvh w-full max-w-3xl flex-col">
      <header className="flex items-center justify-between border-b border-border-subtle px-4 py-3 sm:px-6">
        <h1 className="text-base font-semibold text-text sm:text-lg">Personal AI Assistant</h1>
        <p className="text-xs text-text-muted sm:text-sm">{statusLabel}</p>
      </header>

      <div
        ref={threadRef}
        role="log"
        aria-live="polite"
        aria-busy={busy}
        aria-label="Conversation"
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4 sm:px-6"
      >
        {messages.length === 0 && !busy && (
          <p className="m-auto max-w-sm text-center text-sm text-text-muted">
            Ask anything. Replies stream in as they are generated.
          </p>
        )}
        {messages.map((message) => {
          const isStreaming =
            busy && message.role === "assistant" && message.id === lastId;
          const hasBubble = message.text.length > 0 || isStreaming;
          return (
            <Fragment key={message.id}>
              {message.role === "assistant" && message.activity.length > 0 && (
                <ToolActivityTimeline
                  entries={message.activity}
                  onDecide={decide}
                  decidingId={decidingId}
                />
              )}
              {hasBubble && (
                <ChatMessage
                  role={message.role}
                  text={message.text}
                  isStreaming={isStreaming}
                />
              )}
              {message.role === "assistant" && message.stoppedForApproval && (
                <p className="flex items-center gap-1.5 self-start text-xs text-text-muted">
                  <span
                    aria-hidden="true"
                    className="typing-dot h-1.5 w-1.5 rounded-full bg-warning"
                  />
                  Waiting for your approval
                </p>
              )}
            </Fragment>
          );
        })}
      </div>

      {error && <StatusBanner error={error} onDismiss={dismissError} />}

      <ChatComposer
        draft={draft}
        onDraftChange={setDraft}
        onSubmit={send}
        onStop={stop}
        busy={busy}
      />
    </div>
  );
}